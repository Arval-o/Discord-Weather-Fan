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
SAMPLE_RADIUS = 0.008  # ~0.5 mi in degrees

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

# === HELPER FUNCTIONS ===
def safe_json(url):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"JSON fetch failed: {url} ({r.status_code})")
            return None
        return r.json()
    except Exception as e:
        print("JSON error:", e)
        return None

def get_entry_id(entry):
    return getattr(entry, "id", getattr(entry, "guid", None))

def upload_image(filename):
    url = f"https://www.spc.noaa.gov/products/outlook/{filename}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"Image fetch failed: {url} ({r.status_code})")
            return None
        with open(filename, "wb") as f:
            f.write(r.content)
    except Exception as e:
        print("Image download error:", e)
        return None

    api = f"https://api.github.com/repos/{REPO}/contents/{PAGE_FOLDER}/{filename}"
    headers = {"Authorization": f"token {GH_TOKEN}"}

    r_check = requests.get(api, headers=headers)
    sha = r_check.json().get("sha") if r_check.status_code == 200 else None

    with open(filename, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    payload = {"message": f"update {filename}", "content": content_b64, "branch": BRANCH}
    if sha:
        payload["sha"] = sha

    r_put = requests.put(api, headers=headers, data=json.dumps(payload))
    if r_put.status_code not in [200, 201]:
        print("GitHub upload failed:", r_put.text)

    os.remove(filename)
    gh_url = f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}?t={int(time.time())}"
    print(f"Uploaded {filename} → {gh_url}")
    return gh_url

def get_risk(day, base, point):
    data = safe_json(f"https://www.spc.noaa.gov/products/outlook/{base}.json")
    if not data:
        return "NONE", {"tornado":0,"wind":0,"hail":0,"sig":None}, None, []

    tstm_polygons = []
    if day == 1:
        prob_data = safe_json(f"https://www.spc.noaa.gov/products/outlook/{base}_prob.json")
        if prob_data:
            for f in prob_data.get("features", []):
                if "TSTM" in f["properties"].get("LABEL2","").upper():
                    tstm_polygons.append(f)

    sample_box = box(point.x - SAMPLE_RADIUS, point.y - SAMPLE_RADIUS,
                     point.x + SAMPLE_RADIUS, point.y + SAMPLE_RADIUS)
    sub = {"tornado":0,"wind":0,"hail":0,"sig":None}
    found = []

    for f in data.get("features", []):
        try:
            geom = shape(f["geometry"])
            if geom.intersects(sample_box):
                cat = f["properties"].get("category","NONE")
                found.append(cat)
                if day == 1:
                    sub["tornado"] = max(sub["tornado"], f["properties"].get("tor2pct",0))
                    sub["wind"] = max(sub["wind"], f["properties"].get("wind10pct",0))
                    sub["hail"] = max(sub["hail"], f["properties"].get("hail2pct",0))
                    if f["properties"].get("sig"):
                        sub["sig"] = f["properties"].get("sig")
        except:
            continue

    for f in tstm_polygons:
        try:
            if shape(f["geometry"]).intersects(sample_box):
                found.append("TSTM")
        except:
            continue

    risk = "NONE"
    for r in reversed(RISK_ORDER):
        if r in found:
            risk = r
            break

    higher_candidates = []
    for f in data.get("features", []):
        try:
            geom = shape(f["geometry"])
            cat = f["properties"].get("category","NONE")
            if RISK_ORDER.index(cat) <= RISK_ORDER.index(risk):
                continue
            dist = geom.distance(point) * 69
            higher_candidates.append((cat, dist, geom))
        except:
            continue
    if RISK_ORDER.index("TSTM") > RISK_ORDER.index(risk):
        for f in tstm_polygons:
            try:
                geom = shape(f["geometry"])
                dist = geom.distance(point)*69
                higher_candidates.append(("TSTM", dist, geom))
            except:
                continue

    nearest = None
    if higher_candidates:
        higher_candidates.sort(key=lambda x: x[1])
        best = higher_candidates[0]
        dx = best[2].centroid.x - point.x
        dy = best[2].centroid.y - point.y
        angle = (degrees(atan2(dy, dx)) + 360) % 360
        dirs = ["N","NE","E","SE","S","SW","W","NW"]
        nearest = (best[0], int(best[1]), dirs[int((angle+22.5)//45)%8])

    print(f"Day {day} risk at point: {risk}, tornado={sub['tornado']}, wind={sub['wind']}, hail={sub['hail']}")
    return risk, sub, nearest, found

def trend_text(risk, prev):
    if not prev:
        return f"Risk: {risk}"
    if RISK_ORDER.index(risk) > RISK_ORDER.index(prev):
        return f"Risk: {risk} ⚠️ (up from {prev})"
    elif RISK_ORDER.index(risk) < RISK_ORDER.index(prev):
        return f"Risk: {risk} (down from {prev})"
    return f"Risk: {risk}"

def save_state(data):
    tmp = STATE_FILE + ".tmp"
    with open(tmp,"w") as f:
        json.dump(data,f)
    os.replace(tmp,STATE_FILE)

# === LOAD STATE ===
try:
    with open(STATE_FILE,"r") as f:
        last_id = json.load(f)
except:
    last_id = {}

# === FETCH RSS ===
feed = feedparser.parse(RSS_URL)
entries = feed.entries[::-1]

print("RSS entries:")
for e in entries:
    print(e.title, get_entry_id(e))

# === SELECT DAY 1 ===
day1_to_post = None
for entry in entries:
    title = entry.title.lower().replace("-","").replace(" ","")
    if "day1" in title:
        day1_to_post = (entry, "any")
        break
print("Selected Day 1:", day1_to_post[0].title if day1_to_post else None)

# === SELECT DAY 2/3 ===
day2 = None
day3 = None
for entry in entries:
    title = entry.title.lower().replace("-","").replace(" ","")
    if "day2" in title and not day2:
        day2 = entry
    elif "day3" in title and not day3:
        day3 = entry
print("Selected Day 2:", day2.title if day2 else None)
print("Selected Day 3:", day3.title if day3 else None)

# === BUILD EMBEDS ===
embeds = []
content = ""

# --- DAY 1 ---
if day1_to_post:
    entry, tag = day1_to_post
    img = upload_image(f"day1otlk_2000.png")
    if img:
        risk, sub, nearest, _ = get_risk(1,f"day1otlk_2000",POINT)
        trend = trend_text(risk,last_id.get("1_risk"))
        last_id["1_risk"] = risk
        if risk in ["ENH","MDT"]:
            content = f"<@&{ROLE_ID}>"
        elif risk=="HIGH":
            content = "@everyone"

        lines = [trend]
        if sub["tornado"] or sub["wind"] or sub["hail"]:
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
            "color": RISK_COLORS.get(risk,0x808080),
            "image":{"url":img}
        })
        last_id["1"] = get_entry_id(entry)

# --- DAY 2/3 ---
if day2 and day3:
    id2 = get_entry_id(day2)
    id3 = get_entry_id(day3)

    r2, _, _, _ = get_risk(2,"day2otlk",POINT)
    r3, _, _, _ = get_risk(3,"day3otlk",POINT)

    if id2 != last_id.get("2") or id3 != last_id.get("3") or r2 != last_id.get("2_risk") or r3 != last_id.get("3_risk") or day1_to_post:
        img2 = upload_image("day2otlk.png")
        img3 = upload_image("day3otlk.png")

        if img2 and img3:
            trend2 = trend_text(r2,last_id.get("2_risk"))
            trend3 = trend_text(r3,last_id.get("3_risk"))
            last_id["2_risk"] = r2
            last_id["3_risk"] = r3

            if not content:
                if r2 in ["ENH","MDT"]:
                    content = f"<@&{ROLE_ID}>"
                elif r2=="HIGH":
                    content = "@everyone"

            embeds.append({
                "title":"SPC Day 2 Outlook",
                "url":day2.link,
                "description":trend2,
                "color":RISK_COLORS.get(r2,0x808080),
                "thumbnail":{"url":img2}
            })
            embeds.append({
                "title":"SPC Day 3 Outlook",
                "url":day3.link,
                "description":trend3,
                "color":RISK_COLORS.get(r3,0x808080),
                "thumbnail":{"url":img3}
            })
            last_id["2"] = id2
            last_id["3"] = id3

# === SEND TO DISCORD ===
if embeds:
    final_content = f"<@{MY_ID}>"
    if content:
        final_content += f" {content}"
    print("Posting to Discord with content:", final_content)
    r = requests.post(WEBHOOK_URL,json={"content":final_content,"embeds":embeds})
    if r.status_code==204:
        save_state(last_id)
        print("Posted successfully.")
    else:
        print("Discord post failed:", r.status_code,r.text)
else:
    print("Nothing to post")
