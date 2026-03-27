import feedparser
import requests
import os
import json
import time
import base64
from shapely.geometry import shape, Point

# === CONFIG ===
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]

REPO = "arval-o/Discord-Weather-Fan"
BRANCH = "main"
PAGE_FOLDER = "docs"

STATE_FILE = "last_id.txt"
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"

ROLE_ID = "1485401778962043021"
POINT = Point(-80.096278, 40.615111)

DAY1_PRIORITY = ["2000", "1630", "1300"]

RISK_COLORS = {
    "NONE": 0x808080,
    "TSTM": 0x90ee90,
    "MRGL": 0x006400,
    "SLGT": 0xFFFF00,
    "ENH": 0xFFA500,
    "MDT": 0xFF0000,
    "HIGH": 0xFFC0CB
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

day_entries = {"1": {}, "2": None, "3": None}

for entry in entries:
    t = entry.title.lower()
    if "day 1" in t:
        for p in DAY1_PRIORITY:
            if p in t:
                day_entries["1"][p] = entry
    elif "day 2" in t:
        day_entries["2"] = entry
    elif "day 3" in t:
        day_entries["3"] = entry

# === SELECT DAY 1 ===
day1_to_post = None
last_priority = last_id.get("1_priority", "")

for p in DAY1_PRIORITY:
    e = day_entries["1"].get(p)
    if e:
        if last_priority == "" or DAY1_PRIORITY.index(p) < DAY1_PRIORITY.index(last_priority):
            if e.id != last_id.get("1"):
                day1_to_post = (e, p)
                break

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
        content = base64.b64encode(f.read()).decode()

    payload = {"message": f"update {filename}", "content": content, "branch": BRANCH}
    if sha:
        payload["sha"] = sha

    requests.put(api, headers=headers, data=json.dumps(payload))
    os.remove(filename)

    return f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}?t={int(time.time())}"

# === RISK LOOKUP ===
def get_risk(day, base):
    url = f"https://www.spc.noaa.gov/products/outlook/{base}.json"
    r = requests.get(url)

    if r.status_code != 200:
        return "NONE", {"tornado":0,"wind":0,"hail":0,"sig":None}

    data = r.json()
    risk = "NONE"
    sub = {"tornado":0,"wind":0,"hail":0,"sig":None}

    for f in data.get("features", []):
        g = f.get("geometry")
        if g and shape(g).contains(POINT):
            p = f["properties"]
            risk = p.get("category","NONE")

            if day == 1:
                sub["tornado"] = p.get("tor2pct",0)
                sub["wind"] = p.get("wind10pct",0)
                sub["hail"] = p.get("hail2pct",0)
                sub["sig"] = p.get("sig",None)

    return risk, sub

# === BUILD EMBEDS ===
embeds = []
content = ""

# --- DAY 1 ---
if day1_to_post:
    e, p = day1_to_post
    img = upload_image(f"day1otlk_{p}.png")

    if img:
        risk, sub = get_risk(1, f"day1otlk_{p}")

        if risk in ["ENH","MDT"]:
            content = f"<@&{ROLE_ID}>"
        elif risk == "HIGH":
            content = "@everyone"

        tor = sub["tornado"]
        wind = sub["wind"]
        hail = sub["hail"]
        sig = sub["sig"]

        text = []
        none = []

        if tor == 0: none.append("tornado")
        else: text.append(f"**Tornado: {tor}%**" if tor>=10 or (tor>=5 and sig) else f"Tornado: {tor}%")

        if wind == 0: none.append("wind")
        else: text.append(f"**Wind: {wind}%**" if wind>=30 or (wind>=15 and sig) else f"Wind: {wind}%")

        if hail == 0: none.append("hail")
        else: text.append(f"**Hail: {hail}%**" if hail>=30 or (hail>=15 and sig) else f"Hail: {hail}%")

        if len(none)==3:
            text.append("No tornado, wind, or hail risk.")
        elif none:
            text.append(f"No {' and '.join(none)} risk.")

        embeds.append({
            "title": e.title,
            "url": e.link,
            "description": f"Risk: {risk}\n" + "\n".join(text),
            "color": RISK_COLORS.get(risk,0x808080),
            "image": {"url": img}
        })

        last_id["1"] = e.id
        last_id["1_priority"] = p
        print("Posted Day 1")

# --- DAY 2/3 COMBINED ---
d2 = day_entries["2"]
d3 = day_entries["3"]

if d2 and d3:
    if d2.id != last_id.get("2") and d3.id != last_id.get("3"):

        img2 = upload_image("day2otlk.png")
        img3 = upload_image("day3otlk.png")

        if img2 and img3:
            r2,_ = get_risk(2,"day2otlk")
            r3,_ = get_risk(3,"day3otlk")

            # ping logic
            if not content:
                if r2 in ["ENH","MDT"]:
                    content = f"<@&{ROLE_ID}>"
                elif r2 == "HIGH":
                    content = "@everyone"

            embeds.append({
                "title": "SPC Day 2 Outlook",
                "url": d2.link,
                "description": f"Risk: {r2}",
                "color": RISK_COLORS.get(r2,0x808080),
                "thumbnail": {"url": img2}
            })

            embeds.append({
                "title": "SPC Day 3 Outlook",
                "url": d3.link,
                "description": f"Risk: {r3}",
                "color": RISK_COLORS.get(r3,0x808080),
                "thumbnail": {"url": img3}
            })

            last_id["2"] = d2.id
            last_id["3"] = d3.id

            print("Posted Day 2/3 (combined)")

    else:
        print("Skipping Day 2/3 (not both new)")

# === SEND ===
if embeds:
    MY_ID = "1109224984984956968"

    final_content = f"<@{MY_ID}>"
    if content:
        final_content += f" {content}"
    
    r = requests.post(WEBHOOK_URL, json={"content": final_content, "embeds": embeds})

    if r.status_code == 204:
        with open(STATE_FILE,"w") as f:
            json.dump(last_id,f)
        print("Posted to Discord")
    else:
        print("Discord error:", r.text)
else:
    print("Nothing to post")
