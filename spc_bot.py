import feedparser
import requests
import os
import json
import base64
import time
from shapely.geometry import shape, Point

# === CONFIG ===
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]
REPO = "arval-o/Discord-Weather-Fan"
BRANCH = "main"
PAGE_FOLDER = "docs"
STATE_FILE = "last_id.txt"
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"
ROLE_ID = "1485401778962043021"  # ENH/MDT ping
POINT = Point(-80.096278, 40.615111)  # lon, lat

DAY1_PRIORITY = ["2000", "1630", "1300"]
RISK_COLORS = {
    "NONE": 0x808080,    # gray
    "TSTM": 0x90ee90,    # pale light green
    "MRGL": 0x006400,    # dark green
    "SLGT": 0xFFFF00,    # yellow
    "ENH": 0xFFA500,     # orange
    "MDT": 0xFF0000,     # red
    "HIGH": 0xFFC0CB     # pink
}

# === Load last posted IDs / don't-post state ===
try:
    with open(STATE_FILE, "r") as f:
        last_id = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    last_id = {}

# === Parse RSS feed ===
feed = feedparser.parse(RSS_URL)
entries = feed.entries[::-1]

# --- Organize entries by day ---
day_entries = {"1": {}, "2": None, "3": None}
for entry in entries:
    title = entry.title.lower()
    if "day 1" in title:
        for t in DAY1_PRIORITY:
            if t in title:
                day_entries["1"][t] = entry
                break
    elif "day 2" in title:
        day_entries["2"] = entry
    elif "day 3" in title:
        day_entries["3"] = entry

# --- Select Day 1 to post ---
day1_to_post = None
last_posted_priority = last_id.get("1_priority", "")
for t in DAY1_PRIORITY:
    entry = day_entries["1"].get(t)
    if entry:
        if last_posted_priority == "" or DAY1_PRIORITY.index(t) < DAY1_PRIORITY.index(last_posted_priority):
            day1_to_post = (entry, t)
            break

# === Helper: upload image to GitHub Pages ===
def upload_image(filename):
    url = f"https://www.spc.noaa.gov/products/outlook/{filename}"
    r = requests.get(url)
    if r.status_code != 200:
        print(f"Error downloading {filename}")
        return None
    with open(filename, "wb") as f:
        f.write(r.content)

    api_url = f"https://api.github.com/repos/{REPO}/contents/{PAGE_FOLDER}/{filename}"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    r_check = requests.get(api_url, headers=headers)
    sha = r_check.json().get("sha") if r_check.status_code == 200 else None

    with open(filename, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    payload = {"message": f"Update {filename}", "content": content_b64, "branch": BRANCH}
    if sha:
        payload["sha"] = sha

    r_put = requests.put(api_url, headers=headers, data=json.dumps(payload))
    os.remove(filename)
    if r_put.status_code not in [200, 201]:
        print("GitHub upload failed:", r_put.text)
        return None
    return f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}?t={int(time.time())}"

# === Helper: extract SPC risk for coordinate ===
def get_risk_for_point(day, filename_base):
    geojson_url = f"https://www.spc.noaa.gov/products/outlook/{filename_base}.json"
    r = requests.get(geojson_url)
    if r.status_code != 200:
        return "NONE", {"tornado": 0, "wind": 0, "hail": 0, "sig_cig": None}

    data = r.json()
    risk_level = "NONE"
    sub_risks = {"tornado": 0, "wind": 0, "hail": 0, "sig_cig": None}

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        category = props.get("category", "")
        geom = feature.get("geometry")
        if geom and shape(geom).contains(POINT):
            if category in ["MRGL","SLGT","ENH","MDT","HIGH","TSTM"]:
                risk_level = category
            if day == 1:
                sub_risks["tornado"] = props.get("tor2pct", 0)
                sub_risks["wind"] = props.get("wind10pct", 0)
                sub_risks["hail"] = props.get("hail2pct", 0)
                sub_risks["sig_cig"] = props.get("sig", None)
    return risk_level, sub_risks

# === Prepare embeds ===
embeds = []

# --- Day 1 ---
if day1_to_post:
    entry, t = day1_to_post
    filename = f"day1otlk_{t}.png"
    url = upload_image(filename)
    if url:
        risk, sub_risks = get_risk_for_point(1, f"day1otlk_{t}")
        color = RISK_COLORS.get(risk, 0x808080)
        content = ""
        if risk in ["ENH","MDT"]:
            content = f"<@&{ROLE_ID}>"
        elif risk == "HIGH":
            content = "@everyone"

        tor = sub_risks.get("tornado", 0)
        wind = sub_risks.get("wind", 0)
        hail = sub_risks.get("hail", 0)
        sig = sub_risks.get("sig_cig", None)

        # Build sub-risk text
        sub_text_parts = []
        no_risks = []
        if tor == 0: no_risks.append("tornado")
        else: sub_text_parts.append(f"**Tornado: {tor}%**" if tor>=10 or (tor>=5 and sig and sig>=1) else f"Tornado: {tor}%")
        if wind == 0: no_risks.append("wind")
        else: sub_text_parts.append(f"**Wind: {wind}%**" if wind>=30 or (wind>=15 and sig and sig>=1) else f"Wind: {wind}%")
        if hail == 0: no_risks.append("hail")
        else: sub_text_parts.append(f"**Hail: {hail}%**" if hail>=30 or (hail>=15 and sig and sig>=1) else f"Hail: {hail}%")
        if len(no_risks)==3:
            sub_text_parts.append("No tornado, wind, or hail risk.")
        elif len(no_risks)>0:
            sub_text_parts.append(f"No {' and '.join(no_risks)} risk.")
        sub_text = "\n".join(sub_text_parts)

        embeds.append({
            "title": entry.title,
            "url": entry.link,
            "description": f"SPC Day 1 Convective Outlook\nRisk: {risk}\n{sub_text}",
            "color": color,
            "image": {"url": url}
        })
        last_id["1"] = entry.id
        last_id["1_priority"] = t
        print(f"Prepared Day 1 {t} for posting")

# --- Day 2 ---
if day_entries["2"]:
    entry2 = day_entries["2"]
    fn2 = "day2otlk.png"
    url2 = upload_image(fn2)
    if url2:
        risk2, _ = get_risk_for_point(2, "day2otlk")
        color2 = RISK_COLORS.get(risk2, 0x808080)
        content2 = ""
        if risk2 in ["ENH","MDT"]:
            content2 = f"<@&{ROLE_ID}>"
        elif risk2 == "HIGH":
            content2 = "@everyone"
        embeds.append({
            "title": entry2.title,
            "url": entry2.link,
            "description": f"SPC Day 2 Convective Outlook\nRisk: {risk2}",
            "color": color2,
            "thumbnail": {"url": url2}
        })
        last_id["2"] = entry2.id
        print("Prepared Day 2 embed with thumbnail")

# --- Day 3 ---
if day_entries["3"]:
    entry3 = day_entries["3"]
    fn3 = "day3otlk.png"
    url3 = upload_image(fn3)
    if url3:
        risk3, _ = get_risk_for_point(3, "day3otlk")
        color3 = RISK_COLORS.get(risk3, 0x808080)
        embeds.append({
            "title": entry3.title,
            "url": entry3.link,
            "description": f"SPC Day 3 Convective Outlook\nRisk: {risk3}",
            "color": color3,
            "thumbnail": {"url": url3}
        })
        last_id["3"] = entry3.id
        print("Prepared Day 3 embed with thumbnail")

# --- Post to Discord ---
if embeds:
    r_discord = requests.post(WEBHOOK_URL, json={"content": content, "embeds": embeds})
    if r_discord.status_code == 204:
        print("Posted embed(s) to Discord")
        with open(STATE_FILE, "w") as f:
            json.dump(last_id, f)
    else:
        print("Discord post failed:", r_discord.text)
else:
    print("No new outlooks to post")
