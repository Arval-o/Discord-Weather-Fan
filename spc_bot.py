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
STATE_FILE = "last_ids.json"

RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"

# === Load last posted IDs per day (Day 1, 2, 3 only) ===
try:
    with open(STATE_FILE, "r") as f:
        last_ids = json.load(f)
except FileNotFoundError:
    last_ids = {}  # e.g., {"1": "id", "2": "id", "3": "id"}

# === Parse RSS feed ===
feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries found")
    exit()

# Reverse feed to post oldest first
entries = feed.entries[::-1]

for entry in entries:
    title = entry.title.lower()

    # Determine which day this outlook is
    if "day 1" in title:
        day_key = "1"
        # Determine which Day 1 version
        if "1300" in title:
            filename = "day1otlk_1300.png"
        elif "1630" in title:
            filename = "day1otlk_1630.png"
        elif "2000" in title:
            filename = "day1otlk_2000.png"
        else:
            continue  # skip unknown Day 1 version
    elif "day 2" in title:
        day_key = "2"
        filename = "day2otlk.png"
    elif "day 3" in title:
        day_key = "3"
        filename = "day3otlk.png"
    else:
        # Skip Day 4-8 or any other unknown outlook
        continue

    # Skip if already posted
    if last_ids.get(day_key) == entry.id:
        continue

    image_url = f"https://www.spc.noaa.gov/products/outlook/{filename}"

    # === Download image ===
    r = requests.get(image_url)
    if r.status_code != 200:
        print(f"Error downloading image {filename}")
        continue

    with open(filename, "wb") as f:
        f.write(r.content)

    # === Upload/update GitHub Pages file ===
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
        print("Error uploading to GitHub Pages:", r_put.text)
        os.remove(filename)
        continue

    # === Construct public URL for Discord embed ===
    base_url = f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}"
    public_url = f"{base_url}?t={int(time.time())}"

    # === Post to Discord ===
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
        print("Error posting to Discord:", r_discord.text)
    else:
        print(f"Successfully posted {entry.title} to Discord")

    # === Update last posted ID for this day ===
    last_ids[day_key] = entry.id
    with open(STATE_FILE, "w") as f:
        json.dump(last_ids, f)

    # === Clean up local file ===
    os.remove(filename)
