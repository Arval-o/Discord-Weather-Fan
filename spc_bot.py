import feedparser
import requests
import os
import json
import time
import base64
from shapely.geometry import shape, Point, box
from shapely.ops import nearest_points
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

RISK_EMOJIS = {
    "NONE": "⬜",
    "TSTM": "🟦",
    "MRGL": "🟩",
    "SLGT": "🟨",
    "ENH": "🟧",
    "MDT": "🟥",
    "HIGH": "⚠️"
}

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
    if entry.id == last_id.get("1"):
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
    if "day 2" in t:
        day2 = entry
    elif "day 3" in t:
        day3 = entry

# === IMAGE UPLOAD ===
def upload_image(filename):
    url = f"https://www.spc.noaa.gov/products/outlook/{filename}"
    r = requests.get(url)
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

    payload = {"message": f"update {filename}", "content": content_b64, "branch": BRANCH}
    if sha:
        payload["sha"] = sha

    requests.put(api, headers=headers, data=json.dumps(payload))
    os.remove(filename)

    return f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}?t={int(time.time())}"

# === RISK FUNCTION ===
def get_risk(day, base):
    try:
        data = requests.get(f"https://www.spc.noaa.gov/products/outlook/{base}.json").json()
    except:
        return "NONE", {"tornado":0,"wind":0,"hail":0,"sig":None}, None

    # small box around point for day 1 local risk
    sample_box = box(
        POINT.x - SAMPLE_RADIUS,
        POINT.y - SAMPLE_RADIUS,
        POINT.x + SAMPLE_RADIUS,
        POINT.y + SAMPLE_RADIUS
    )

    sub = {"tornado":0,"wind":0,"hail":0,"sig":None}
    local_categories = []

    # --- local risk ---
    for f in data.get("features", []):
        try:
            geom = shape(f["geometry"])
            cat = f["properties"].get("category", "NONE")
            if geom.intersects(sample_box):
                local_categories.append(cat)
                if day == 1:
                    sub["tornado"] = f["properties"].get("tor2pct",0)
                    sub["wind"] = f["properties"].get("wind10pct",0)
                    sub["hail"] = f["properties"].get("hail2pct",0)
                    sub["sig"] = f["properties"].get("sig",None)
        except:
            continue

    # determine main risk
    risk = "NONE"
    for r in reversed(RISK_ORDER):
        if r in local_categories:
            risk = r
            break

    # --- nearest higher risk ---
    candidates = []
    local_index = RISK_ORDER.index(risk)

    for f in data.get("features", []):
        try:
            geom = shape(f["geometry"])
            cat = f["properties"].get("category", "NONE")
            cat_index = RISK_ORDER.index(cat)
            if cat_index <= local_index:
                continue  # skip lower/equal
            # true closest point on polygon
            _, nearest_point = nearest_points(POINT, geom)
            dist = POINT.distance(nearest_point) * 69  # degrees → miles
            candidates.append((dist, nearest_point, cat))
        except:
            continue

    nearest = None
    if candidates:
        candidates.sort(key=lambda x: x[0])  # closest first
        best = candidates[0]
        dx = best[1].x - POINT.x
        dy = best[1].y - POINT.y
        angle = (degrees(atan2(dy, dx)) + 360) % 360
        dirs = ["N","NE","E","SE","S","SW","W","NW"]
        direction = dirs[int((angle+22.5)//45)%8]
        nearest = (best[2], int(best[0]), direction)

    return risk, sub, nearest

# === TREND FORMAT ===
def format_risk(risk, prev):
    base = f"{RISK_EMOJIS[risk]} Risk: {risk}"
    if prev and prev != risk:
        if RISK_ORDER.index(risk) > RISK_ORDER.index(prev):
            return f"{RISK_EMOJIS[risk]} Risk: {risk} (**⚠️ up from {prev}**)"
        else:
            return f"{RISK_EMOJIS[risk]} Risk: {risk} (down from {prev})"
    return base

# === BUILD EMBEDS ===
embeds = []
content = ""

# --- DAY 1 ---
if day1_to_post:
    entry, tag = day1_to_post
    img = upload_image(f"day1otlk_{tag}.png")

    if img:
        risk, sub, nearest = get_risk(1, f"day1otlk_{tag}")

        risk_text = format_risk(risk, last_id.get("1_risk"))
        last_id["1_risk"] = risk

        if risk in ["ENH","MDT"]:
            content = f"<@&{ROLE_ID}>"
        elif risk == "HIGH":
            content = "@everyone"

        lines = [risk_text]

        if sub["tornado"]: lines.append(f"Tornado: {sub['tornado']}%")
        if sub["wind"]: lines.append(f"Wind: {sub['wind']}%")
        if sub["hail"]: lines.append(f"Hail: {sub['hail']}%")
        if not (sub["tornado"] or sub["wind"] or sub["hail"]):
            lines.append("No tornado, wind, or hail risk.")

        if nearest:
            lines.append(f"Next higher risk: {nearest[0]} (~{nearest[1]} mi {nearest[2]})")
        else:
            lines.append("No higher risk levels in CONUS.")

        embeds.append({
            "title": entry.title,
            "url": entry.link,
            "description": "\n".join(lines),
            "color": RISK_COLORS[risk],
            "image": {"url": img}
        })

        last_id["1"] = entry.id
        last_id["1_priority"] = tag

# --- DAY 2/3 ---
if day2 and day3:
    if day2.id != last_id.get("2") and day3.id != last_id.get("3"):

        img2 = upload_image("day2otlk.png")
        img3 = upload_image("day3otlk.png")

        if img2 and img3:
            r2, _, _ = get_risk(2, "day2otlk")
            r3, _, _ = get_risk(3, "day3otlk")

            text2 = format_risk(r2, last_id.get("2_risk"))
            text3 = format_risk(r3, last_id.get("3_risk"))

            last_id["2_risk"] = r2
            last_id["3_risk"] = r3

            embeds.append({
                "title": "SPC Day 2 Outlook",
                "url": day2.link,
                "description": text2,
                "color": RISK_COLORS[r2],
                "thumbnail": {"url": img2}
            })

            embeds.append({
                "title": "SPC Day 3 Outlook",
                "url": day3.link,
                "description": text3,
                "color": RISK_COLORS[r3],
                "thumbnail": {"url": img3}
            })

            last_id["2"] = day2.id
            last_id["3"] = day3.id

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
        with open(STATE_FILE, "w") as f:
            json.dump(last_id, f)
        print("Posted to Discord")
    else:
        print("Discord error:", r.text)
else:
    print("Nothing to post")
