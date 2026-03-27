import feedparser
import requests
import os
import json
import base64
import time

# === CONFIGURATION ===
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]
REPO = "arval-o/Discord-Weather-Fan"
BRANCH = "main"
PAGE_FOLDER = "docs"
STATE_FILE = "last_id.txt"
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"

# Day 1 priority order
DAY1_PRIORITY = ["2000", "1630", "1300"]

# === Load last posted IDs per day ===
try:
    with open(STATE_FILE, "r") as f:
        last_id = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    last_id = {}

# === Parse RSS feed ===
feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries found")
    exit()

# Reverse so oldest first
entries = feed.entries[::-1]

# Separate entries by day
day_entries = {"1": {}, "2": {}, "3": {}}
for entry in entries:
    title = entry.title.lower()
    if "day 1" in title:
        for t in DAY1_PRIORITY:
            if t in title:
                day_entries["1"][t] = entry
                break
    elif "day 2" in title:
        day_entries["2"]["day2"] = entry
    elif "day 3" in title:
        day_entries["3"]["day3"] = entry

# === Select Day 1 entry to post ===
day1_to_post = None
for t in DAY1_PRIORITY:
    entry = day_entries["1"].get(t)
    if entry and last_id.get("1") != entry.id:
        day1_to_post = (entry, t)
        break

# === Determine Day 2/3 entries to post ===
day2_to_post = day_entries["2"].get("day2")
day3_to_post = day_entries["3"].get("day3")

# Skip if already posted
if day2_to_post and last_id.get("2") == day2_to_post.id:
    day2_to_post = None
if day3_to_post and last_id.get("3") == day3_to_post.id:
    day3_to_post = None

# --- Helper: upload image to GitHub Pages ---
def upload_image(filename):
    image_url = f"https://www.spc.noaa.gov/products/outlook/{filename}"
    r = requests.get(image_url)
    if r.status_code != 200:
        print(f"Error downloading {filename}")
        return None
    with open(filename, "wb") as f:
        f.write(r.content)

    api_url = f"https://api.github.com/repos/{REPO}/contents/{PAGE_FOLDER}/{filename}"
    headers = {"Authorization": f"token {GH_TOKEN}"}

    # Refresh SHA immediately before PUT
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

    public_url = f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}?t={int(time.time())}"
    return public_url

# === Prepare Discord embeds ===
embeds = []

# Day 1 embed
if day1_to_post:
    entry, t = day1_to_post
    filename = f"day1otlk_{t}.png"
    public_url = upload_image(filename)
    if public_url:
        embeds.append({
            "title": entry.title,
            "url": entry.link,
            "image": {"url": public_url},
            "description": "SPC Convective Outlook",
            "color": 16711680
        })
        last_id["1"] = entry.id
        print(f"Prepared Day 1 {t} for posting")

# Day 2/3 embed (combine if both exist)
if day2_to_post or day3_to_post:
    description = ""
    for entry, day in [(day2_to_post, "2"), (day3_to_post, "3")]:
        if entry:
            description += f"**Day {day} Convective Outlook**\n[{entry.title}]({entry.link})\n\n"
            last_id[day] = entry.id
    embeds.append({
        "title": "SPC Day 2/3 Outlook",
        "description": description.strip(),
        "color": 65280
    })
    print("Prepared Day 2/3 embed for posting")

# === Post to Discord if any embeds exist ===
if embeds:
    payload = {"embeds": embeds}
    r_discord = requests.post(WEBHOOK_URL, json=payload)
    if r_discord.status_code == 204:
        print("Posted embed(s) to Discord")
        with open(STATE_FILE, "w") as f:
            json.dump(last_id, f)
    else:
        print("Discord post failed:", r_discord.text)
else:
    print("No new outlooks to post")
