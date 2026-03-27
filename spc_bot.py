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

# === Load last posted IDs per day (also acts as don't-post list) ===
try:
    with open(STATE_FILE, "r") as f:
        content = f.read().strip()
        last_id = json.loads(content) if content else {}
except (FileNotFoundError, json.JSONDecodeError):
    last_id = {}

# === Parse RSS feed ===
feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries found")
    exit()

# === Collect newest entries per day ===
newest_per_day = {}

# Day 1 priority: post only the latest time (2000 > 1630 > 1300)
day1_priority = ["2000", "1630", "1300"]

for entry in feed.entries:
    title_lower = entry.title.lower()
    day_key = None
    filename = None

    if "day 1" in title_lower:
        day_key = "1"
        for t in day1_priority:
            if t in title_lower:
                filename = f"day1otlk_{t}.png"
                break
    elif "day 2" in title_lower:
        day_key = "2"
        filename = "day2otlk.png"
    elif "day 3" in title_lower:
        day_key = "3"
        filename = "day3otlk.png"
    else:
        continue  # skip Day 4-8

    if not filename:
        continue

    # Skip if in last_id (acts as don't-post list)
    if last_id.get(day_key) == entry.id:
        print(f"Skipping {entry.title} (already posted / don't post)")
        continue

    # For Day 1, keep only the highest-priority outlook
    if day_key in newest_per_day:
        if day_key == "1":
            current_priority = day1_priority.index(filename.split("_")[1].split(".")[0])
            existing_priority = day1_priority.index(newest_per_day[day_key]['filename'].split("_")[1].split(".")[0])
            if current_priority > existing_priority:
                # Current is lower priority than existing, skip it
                continue
            else:
                # Current is higher priority, replace existing
                newest_per_day[day_key] = {"entry": entry, "filename": filename}
        else:
            continue  # Day 2/3: keep first found
    else:
        newest_per_day[day_key] = {"entry": entry, "filename": filename}
    
# === Post newest entries per day ===
for day_key, data in newest_per_day.items():
    entry = data["entry"]
    filename = data["filename"]

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

    time.sleep(10)
    r_discord = requests.post(WEBHOOK_URL, json=embed_data)
    if r_discord.status_code != 204:
        print("Discord post failed:", r_discord.text)
    else:
        print(f"Posted {entry.title} to Discord")

    # Update last posted ID (acts as don't-post record)
    last_id[day_key] = entry.id
    with open(STATE_FILE, "w") as f:
        json.dump(last_id, f)

    # Clean up local file
    os.remove(filename)
