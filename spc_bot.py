import feedparser
import requests
import os
import json
import base64

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

latest = feed.entries[0]

# Only post if new
if latest.id == last_id:
    print("Already posted latest outlook")
    exit()

last_id = latest.id
title = latest.title.lower()

# === Determine correct SPC image URL and filename ===
filename = None
image_url = None

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
    print("No matching image for latest outlook")
    exit()

# === Download the SPC image ===
r = requests.get(image_url)
if r.status_code != 200:
    print("Error downloading image")
    exit()

with open(filename, "wb") as f:
    f.write(r.content)

# === GitHub API: upload/update file in /docs ===
api_url = f"https://api.github.com/repos/{REPO}/contents/{PAGE_FOLDER}/{filename}"
headers = {"Authorization": f"token {GH_TOKEN}"}

# Check if file exists (to get SHA)
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
    exit()

# === Construct public URL for Discord embed ===
public_url = f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{filename}"

# === Post to Discord ===
embed_data = {
    "embeds": [
        {
            "title": latest.title,
            "url": latest.link,
            "image": {"url": public_url},
            "description": "SPC Convective Outlook",
            "color": 16711680
        }
    ]
}

r_discord = requests.post(WEBHOOK_URL, json=embed_data)
if r_discord.status_code != 204:
    print("Error posting to Discord:", r_discord.text)
else:
    print("Successfully posted SPC outlook to Discord")

# === Save last posted ID ===
with open(STATE_FILE, "w") as f:
    f.write(latest.id)

# === Clean up local file ===
os.remove(filename)
