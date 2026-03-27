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

# === Load last posted ID ===
try:
    with open(STATE_FILE, "r") as f:
        last_id = f.read().strip()
except FileNotFoundError:
    last_id = ""

# === Parse RSS feed ===
feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries found")
    exit()

# Reverse feed to post oldest first
entries = feed.entries[::-1]

for entry in entries:
    if entry.id == last_id:
        continue  # already posted

    title = entry.title.lower()
    filename = None
    image_url = None

    # === Determine correct SPC image URL and filename ===
    if "day 1" in title:
        if "1300" in title:
            image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk_1300.png"
            filename = "day1otlk_1300.png"
        elif "1630" in title:
            image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk_1630.png"
            filename = "day1otlk_1630.png"
        elif "2000" in title:
            image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk_2000.png"
            filename = "day1otlk_2000.png"
    elif "day 2" in title:
        image_url = "https://www.spc.noaa.gov/products/outlook/day2otlk.png"
        filename = "day2otlk.png"
    elif "day 3" in title:
        image_url = "https://www.spc.noaa.gov/products/outlook/day3otlk.png"
        filename = "day3otlk.png"

    if not image_url or not filename:
        print(f"No matching image for {entry.title}")
        continue

    # === Download the SPC image ===
    r = requests.get(image_url)
    if r.status_code != 200:
        print(f"Error downloading image {filename}")
        continue

    with open(filename, "wb") as f:
        f.write(r.content)

    # === GitHub API: upload/update file in /docs ===
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
    time.sleep(5)  # small delay to avoid rate limits
    r_discord = requests.post(WEBHOOK_URL, json=embed_data)
    if r_discord.status_code != 204:
        print("Error posting to Discord:", r_discord.text)
    else:
        print(f"Successfully posted {entry.title} to Discord")

    # === Update last posted ID ===
    last_id = entry.id
    with open(STATE_FILE, "w") as f:
        f.write(last_id)

    # === Clean up local file ===
    os.remove(filename)
