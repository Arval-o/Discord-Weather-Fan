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

# === Load last posted IDs per day ===
try:
    with open(STATE_FILE, "r") as f:
        last_id = json.load(f)
except FileNotFoundError:
    last_id = {}  # keys: "1", "2", "3"

# === Parse RSS feed ===
feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries found")
    exit()

# Process oldest to newest to avoid skipping
entries = feed.entries[::-1]

for entry in entries:
    title = entry.title.lower()

    # Determine day and filename
    day_key = None
    filename = None

    if "day 1" in title:
        day_key = "1"
        if "1300" in title:
            filename = "day1otlk_1300.png"
        elif "1630" in title:
            filename = "day1otlk_1630.png"
        elif "2000" in title:
            filename = "day1otlk_2000.png"
        else:
            continue
    elif "day 2" in title:
        day_key = "2"
        filename = "day2otlk.png"
    elif "day 3" in title:
        day_key = "3"
        filename = "day3otlk.png"
    else:
        continue  # skip Day 4-8

    # Check last posted ID for this day
    if last_id.get(day_key) == entry.id:
        print(f"Skipping already posted {entry.title}")
        continue

    image_url = f"https://www.spc.noaa.gov/products/outlook/{filename}"

    # Download image
    r = requests.get(image_url)
    if r.status_code != 200:
        print(f"Error downloading {filename}")
        continue

    with open(filename, "wb") as f:
        f.write(r.content)

    # Upload/update GitHub Pages
    api_url = f"https://api.github.com/repos/{REPO}/contents/{PAGE_FOLDER}/{filename}"
    headers = {"Authorization": f"token {GH_TOKEN}"}

    r_check = requests.get(api_url, headers=headers)
    sha = r_check.json().get("sha") if r_check.status_code == 200 else None

    with open(filename, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "message": f"Update {filename}",
        "content": content_b64,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha

    r_put = requests.put(api_url, headers=headers, data=json.dumps(payload))
    if r_put.status_code not in [200, 201]:
        print("GitHub upload failed:", r_put.text)
        os.remove(filename)
        continue

    # Post to Discord
    public_url = f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}?t={int(time.time())}"
    embed_data = {
        "embeds": [
            {
                "title": entry.title,
                "url": entry.link,
                "image": {"url": public_url},
                "description": "SPC Convective Outlook",
                "color": 16711680
            }
        ]
    }

    time.sleep(5)
    r_discord = requests.post(WEBHOOK_URL, json=embed_data)
    if r_discord.status_code != 204:
        print("Discord post failed:", r_discord.text)
    else:
        print(f"Posted {entry.title} to Discord")

    # Update last posted ID only after successful post
    last_id[day_key] = entry.id
    with open(STATE_FILE, "w") as f:
        json.dump(last_id, f)

    # Clean up local file
    os.remove(filename)
