import feedparser
import requests
import os
import json
import time
import base64
from shapely.geometry import shape, Point, box
from math import atan2, degrees

# === CONFIG ===
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]

REPO = "arval-o/Discord-Weather-Fan"
BRANCH = "main"
PAGE_FOLDER = "docs"
STATE_FILE = "last_id.txt"
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"

ROLE_ID = "1485401778962043021"
MY_ID = "1109224984984956968"

POINT = Point(-80.096278, 40.615111)
SAMPLE_RADIUS = 0.008

PRIORITY_ORDER = ["2000", "1630", "1300", "0600", "0100"]
RISK_ORDER = ["NONE", "TSTM", "MRGL", "SLGT", "ENH", "MDT", "HIGH"]

RISK_COLORS = {
    "NONE": 0x808080,
    "TSTM": 0x90ee90,
    "MRGL": 0x006400,
    "SLGT": 0xFFFF00,
    "ENH": 0xFFA500,
    "MDT": 0xFF0000,
    "HIGH": 0xFF0000
}

# === SAFE JSON FETCH ===
def safe_json(url):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        print("JSON fetch error:", e)
        return None

# === LOAD STATE ===
try:
    with open(STATE_FILE, "r") as f:
        last_id = json.load(f)
except:
    last_id = {}

# === FETCH RSS ===
feed = feedparser.parse(RSS_URL)
entries = feed.entries[::-1]

# === DAY 1 COLLECTION ===
day1_all = []
for entry in entries:
    t = entry.title.lower()
    if "day 1" in t:
        for tag in PRIORITY_ORDER:
            if tag in t:
                day1_all.append((tag, entry))

day1_all.sort(key=lambda x: PRIORITY_ORDER.index(x[0]))

day1_to_post = None
last_priority = last_id.get("1_priority")

for tag, entry in day1_all:
    entry_id = getattr(entry, "id", getattr(entry, "guid", None))
    if entry_id == last_id.get("1"):
        continue
    if last_priority and PRIORITY_ORDER.index(tag) > PRIORITY_ORDER.index(last_priority):
        continue
    day1_to_post = (entry, tag)
    break

# === DAY 2/3 ===
day2 = None
day3 = None

for entry in entries:
    t = entry.title.lower()
    if "day 2" in t and not day2:
        day2 = entry
    elif "day 3" in t and not day3:
        day3 = entry

# === IMAGE UPLOAD ===
def upload_image(filename):
    url = f"https://www.spc.noaa.gov/products/outlook/{filename}"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return None

    with open(filename, "wb") as f:
        f.write(r.content)

    api = f"https://api.github.com/repos/{REPO}/contents/{PAGE_FOLDER}/{filename}"
    headers = {"Authorization": f"token {GH_TOKEN}"}

    r_check = requests.get(api, headers=headers)
    sha = r_check.json().get("sha") if r_check.status_code == 200 else None

    with open(filename, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "message": f"update {filename}",
        "content": content_b64,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha

    r_put = requests.put(api, headers=headers, data=json.dumps(payload))
    if r_put.status_code not in [200, 201]:
        print("GitHub upload failed:", r_put.text)

    os.remove(filename)

    return f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}?t={int(time.time())}"

# === RISK FUNCTION ===
def get_risk(day, base, point):
    data = safe_json(f"https://www.spc.noaa.gov/products/outlook/{base}.json")
    if not data:
        return "NONE", {"tornado": 0, "wind": 0, "hail": 0, "sig": None}, None, []

    tstm_polygons = []
    if day == 1:
        prob_data = safe_json(f"https://www.spc.noaa.gov/products/outlook/{base}_prob.json")
        if prob_data:
            for f in prob_data.get("features", []):
                if "TSTM" in f["properties"].get("LABEL2", "").upper():
                    tstm_polygons.append(f)

    sample_box = box(point.x - SAMPLE_RADIUS, point.y - SAMPLE_RADIUS,
                     point.x + SAMPLE_RADIUS, point.y + SAMPLE_RADIUS)

    sub = {"tornado": 0, "wind": 0, "hail": 0, "sig": None}
    found = []

    for f in data.get("features", []):
        try:
            geom = shape(f["geometry"])
            if geom.intersects(sample_box):
                cat = f["properties"].get("category", "NONE")
                found.append(cat)

                if day == 1:
                    sub["tornado"] = max(sub["tornado"], f["properties"].get("tor2pct", 0))
                    sub["wind"] = max(sub["wind"], f["properties"].get("wind10pct", 0))
                    sub["hail"] = max(sub["hail"], f["properties"].get("hail2pct", 0))
                    if f["properties"].get("sig"):
                        sub["sig"] = f["properties"].get("sig")
        except Exception as e:
            print("Geom error:", e)

    for f in tstm_polygons:
        try:
            if shape(f["geometry"]).intersects(sample_box):
                found.append("TSTM")
        except Exception:
            pass

    risk = "NONE"
    for r in reversed(RISK_ORDER):
        if r in found:
            risk = r
            break

    # nearest higher
    higher_candidates = []

    for f in data.get("features", []):
        try:
            geom = shape(f["geometry"])
            cat = f["properties"].get("category", "NONE")
            if RISK_ORDER.index(cat) <= RISK_ORDER.index(risk):
                continue
            dist = geom.distance(point) * 69
            higher_candidates.append((cat, dist, geom))
        except Exception:
            pass

    if RISK_ORDER.index("TSTM") > RISK_ORDER.index(risk):
        for f in tstm_polygons:
            try:
                geom = shape(f["geometry"])
                dist = geom.distance(point) * 69
                higher_candidates.append(("TSTM", dist, geom))
            except:
                pass

    nearest = None
    if higher_candidates:
        higher_candidates.sort(key=lambda x: x[1])
        best = higher_candidates[0]

        dx = best[2].centroid.x - point.x
        dy = best[2].centroid.y - point.y
        angle = (degrees(atan2(dy, dx)) + 360) % 360

        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        nearest = (best[0], int(best[1]), dirs[int((angle + 22.5) // 45) % 8])

    return risk, sub, nearest, found

# === SAVE STATE SAFELY ===
def save_state(data):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, STATE_FILE)

# === BUILD EMBEDS ===
embeds = []
content = ""

def trend_text(risk, prev):
    if not prev:
        return f"Risk: {risk}"
    if RISK_ORDER.index(risk) > RISK_ORDER.index(prev):
        return f"Risk: {risk} ⚠️ (up from {prev})"
    elif RISK_ORDER.index(risk) < RISK_ORDER.index(prev):
        return f"Risk: {risk} (down from {prev})"
    return f"Risk: {risk}"

# --- DAY 1 ---
if day1_to_post:
    entry, tag = day1_to_post
    img = upload_image(f"day1otlk_{tag}.png")

    if img:
        risk, sub, nearest, _ = get_risk(1, f"day1otlk_{tag}", POINT)

        trend = trend_text(risk, last_id.get("1_risk"))
        last_id["1_risk"] = risk

        if risk in ["ENH", "MDT"]:
            content = f"<@&{ROLE_ID}>"
        elif risk == "HIGH":
            content = "@everyone"

        lines = [trend]

        if any(sub.values()):
            if sub["tornado"]: lines.append(f"Tornado: {sub['tornado']}%")
            if sub["wind"]: lines.append(f"Wind: {sub['wind']}%")
            if sub["hail"]: lines.append(f"Hail: {sub['hail']}%")
        else:
            lines.append("No tornado, wind, or hail risk.")

        if nearest:
            lines.append(f"Nearest higher risk: {nearest[0]} (~{nearest[1]} mi {nearest[2]})")
        else:
            lines.append("No higher risk levels in CONUS.")

        embeds.append({
            "title": entry.title,
            "url": entry.link,
            "description": "\n".join(lines),
            "color": RISK_COLORS.get(risk, 0x808080),
            "image": {"url": img}
        })

        last_id["1"] = getattr(entry, "id", getattr(entry, "guid", None))
        last_id["1_priority"] = tag

# --- DAY 2/3 ---
if day2 and day3:
    id2 = getattr(day2, "id", getattr(day2, "guid", None))
    id3 = getattr(day3, "id", getattr(day3, "guid", None))

    if id2 != last_id.get("2") or id3 != last_id.get("3"):
        img2 = upload_image("day2otlk.png")
        img3 = upload_image("day3otlk.png")

        if img2 and img3:
            r2, _, _, _ = get_risk(2, "day2otlk", POINT)
            r3, _, _, _ = get_risk(3, "day3otlk", POINT)

            trend2 = trend_text(r2, last_id.get("2_risk"))
            trend3 = trend_text(r3, last_id.get("3_risk"))

            last_id["2_risk"] = r2
            last_id["3_risk"] = r3

            if not content:
                if r2 in ["ENH", "MDT"]:
                    content = f"<@&{ROLE_ID}>"
                elif r2 == "HIGH":
                    content = "@everyone"

            embeds.append({
                "title": "SPC Day 2 Outlook",
                "url": day2.link,
                "description": trend2,
                "color": RISK_COLORS.get(r2, 0x808080),
                "thumbnail": {"url": img2}
            })

            embeds.append({
                "title": "SPC Day 3 Outlook",
                "url": day3.link,
                "description": trend3,
                "color": RISK_COLORS.get(r3, 0x808080),
                "thumbnail": {"url": img3}
            })

            last_id["2"] = id2
            last_id["3"] = id3

# === SEND ===
if embeds:
    final_content = f"<@{MY_ID}>"
    if content:
        final_content += f" {content}"

    r = requests.post(WEBHOOK_URL, json={
        "content": final_content,
        "embeds": embeds
    })

    if r.status_code == 204:
        save_state(last_id)
        print("Posted to Discord")
    else:
        print("Discord error:", r.text)
else:
    print("Nothing to post")
