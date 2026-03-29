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

# Your coordinate
POINT = Point(-80.096278, 40.615111)
SAMPLE_RADIUS = 0.008  # ~0.5 mi in degrees

PRIORITY_ORDER = ["2000","1630","1300","0600","0100"]

# Risk colors and emojis
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
    "NONE": "⚪",
    "TSTM": "🟢",
    "MRGL": "🟩",
    "SLGT": "🟨",
    "ENH": "🟧",
    "MDT": "🟥",
    "HIGH": "⚠️"
}

# === LOAD STATE ===
try:
    with open(STATE_FILE,"r") as f:
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

# === DAY 2/3 COLLECTION ===
day2 = None
day3 = None
for entry in entries:
    t = entry.title.lower()
    if "day 2" in t:
        day2 = entry
    elif "day 3" in t:
        day3 = entry

# === IMAGE UPLOAD + DOT ===
def upload_image(filename, dot=False):
    url = f"https://www.spc.noaa.gov/products/outlook/{filename}"
    r = requests.get(url)
    if r.status_code != 200:
        return None
    with open(filename,"wb") as f:
        f.write(r.content)

    # Optionally add a dot in the middle (your point)
    if dot:
        try:
            from PIL import Image, ImageDraw
            im = Image.open(filename)
            w,h = im.size
            # approximate location as % of width/height
            px = int(w*0.5)
            py = int(h*0.5)
            draw = ImageDraw.Draw(im)
            draw.ellipse((px-5,py-5,px+5,py+5), fill=(255,0,0))
            im.save(filename)
        except ImportError:
            pass

    api = f"https://api.github.com/repos/{REPO}/contents/{PAGE_FOLDER}/{filename}"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    r_check = requests.get(api, headers=headers)
    sha = r_check.json().get("sha") if r_check.status_code==200 else None

    with open(filename,"rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    payload = {"message": f"update {filename}", "content": content_b64, "branch": BRANCH}
    if sha: payload["sha"] = sha
    requests.put(api, headers=headers, data=json.dumps(payload))
    os.remove(filename)

    return f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}?t={int(time.time())}"

# === RISK FUNCTION ===
def get_risk(day, base):
    try:
        data = requests.get(f"https://www.spc.noaa.gov/products/outlook/{base}.json").json()
    except:
        return "NONE", {}, None, None

    sample_box = box(POINT.x-SAMPLE_RADIUS, POINT.y-SAMPLE_RADIUS,
                     POINT.x+SAMPLE_RADIUS, POINT.y+SAMPLE_RADIUS)
    sub = {"tornado":0,"wind":0,"hail":0,"sig":None}
    order = ["NONE","TSTM","MRGL","SLGT","ENH","MDT","HIGH"]
    found = []

    for f in data.get("features", []):
        try:
            geom = shape(f["geometry"])
            if geom.intersects(sample_box):
                cat = f["properties"].get("category","NONE")
                found.append(cat)
                if day==1:
                    sub["tornado"] = max(sub["tornado"], f["properties"].get("tor2pct",0))
                    sub["wind"] = max(sub["wind"], f["properties"].get("wind10pct",0))
                    sub["hail"] = max(sub["hail"], f["properties"].get("hail2pct",0))
                    sub["sig"] = f["properties"].get("sig",sub["sig"])
        except: continue

    # main risk
    risk = "NONE"
    for r in reversed(order):
        if r in found:
            risk = r
            break

    # nearest higher
    candidates = []
    for f in data.get("features", []):
        try:
            geom = shape(f["geometry"])
            cat = f["properties"].get("category","NONE")
            if order.index(cat) <= order.index(risk):
                continue
            dist = geom.distance(POINT)*69
            candidates.append((cat, dist, geom.area, geom))
        except: continue
    nearest = None
    if candidates:
        candidates.sort(key=lambda x:(-order.index(x[0]), -x[2], x[1]))
        best = candidates[0]
        dx = best[3].centroid.x - POINT.x
        dy = best[3].centroid.y - POINT.y
        angle = (degrees(atan2(dy, dx)) + 360) % 360
        dirs = ["N","NE","E","SE","S","SW","W","NW"]
        nearest = (best[0], int(best[1]), dirs[int((angle+22.5)//45)%8])
    return risk, sub, nearest, found

# === BUILD EMBEDS ===
embeds = []
content = ""

# --- DAY 1 ---
if day1_to_post:
    entry, tag = day1_to_post
    print(f"Prepared Day 1 {tag}")
    img = upload_image(f"day1otlk_{tag}.png", dot=True)
    if img:
        risk, sub, nearest, found = get_risk(1,f"day1otlk_{tag}")
        prev_risk = last_id.get("1_risk")
        trend = ""
        if prev_risk and prev_risk != risk:
            trend = f"Trend: {risk} higher than {prev_risk}" if RISK_COLORS[risk]>RISK_COLORS[prev_risk] else f"Trend: {risk} lower than {prev_risk}"
        last_id["1_risk"] = risk

        if risk in ["ENH","MDT"]: content = f"<@&{ROLE_ID}>"
        elif risk=="HIGH": content = "@everyone"

        lines = [f"{RISK_EMOJIS[risk]} Risk: {risk}"]
        tor, wind, hail, sig = sub["tornado"], sub["wind"], sub["hail"], sub["sig"]
        if tor or wind or hail:
            if tor: lines.append(f"Tornado: {tor}%")
            if wind: lines.append(f"Wind: {wind}%")
            if hail: lines.append(f"Hail: {hail}%")
        else:
            lines.append("No tornado, wind, or hail risk.")
        if nearest:
            lines.append(f"Nearest higher risk: {nearest[0]} (~{nearest[1]} mi {nearest[2]})")
        if trend: lines.append(trend)

        embeds.append({
            "title": entry.title,
            "url": entry.link,
            "description": "\n".join(lines),
            "color": RISK_COLORS.get(risk,0x808080),
            "image":{"url":img}
        })
        last_id["1"] = entry.id
        last_id["1_priority"] = tag

# --- DAY 2/3 ---
if day2 and day3:
    if day2.id != last_id.get("2") and day3.id != last_id.get("3"):
        print("Prepared Day 2/3")
        img2 = upload_image("day2otlk.png")
        img3 = upload_image("day3otlk.png")
        if img2 and img3:
            r2,_,_,found2 = get_risk(2,"day2otlk")
            r3,_,_,found3 = get_risk(3,"day3otlk")
            if not content:
                if r2 in ["ENH","MDT"]: content = f"<@&{ROLE_ID}>"
                elif r2=="HIGH": content = "@everyone"
            embeds.append({
                "title":"SPC Day 2 Outlook",
                "url":day2.link,
                "description":f"{RISK_EMOJIS[r2]} Risk: {r2}",
                "color":RISK_COLORS.get(r2,0x808080),
                "thumbnail":{"url":img2}
            })
            embeds.append({
                "title":"SPC Day 3 Outlook",
                "url":day3.link,
                "description":f"{RISK_EMOJIS[r3]} Risk: {r3}",
                "color":RISK_COLORS.get(r3,0x808080),
                "thumbnail":{"url":img3}
            })
            last_id["2"] = day2.id
            last_id["3"] = day3.id

# === SEND TO DISCORD ===
if embeds:
    final_content = f"<@{MY_ID}>"
    if content:
        final_content += f" {content}"
    r = requests.post(WEBHOOK_URL,json={"content":final_content,"embeds":embeds})
    if r.status_code==204:
        with open(STATE_FILE,"w") as f:
            json.dump(last_id,f)
        print("Posted to Discord")
    else:
        print("Discord error:",r.text)
else:
    print("Nothing to post")
