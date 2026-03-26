import feedparser
import requests
import os
from pathlib import Path
import base64
import json

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]
REPO = "arval-o.github.io/Discord-Weather-Fan/" 
BRANCH = "main"         
PAGE_FOLDER = "docs"    
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"
STATE_FILE = "last_id.txt"

# Load last posted ID
try:
    with open(STATE_FILE, "r") as f:
        last_id = f.read().strip()
except:
    last_id = ""

feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries in RSS feed")
    exit()

latest = feed.entries[0]

if latest.id == last_id:
    print("Already posted latest outlook")
    exit()

last_id = latest.id

# Determine SPC image URL
title = latest.title.lower()
image_url = None
filename = None

if "day 1" in title:
    image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk.gif"
    filename = "day1otlk.gif"
elif "day 2" in title:
    image_url = "https://www.spc.noaa.gov/products/outlook/day2otlk.gif"
    filename = "day2otlk.gif"
elif "day 3" in title:
    image_url = "https://www.spc.noaa.gov/products/outlook/day3otlk.gif"
    filename = "day3otlk.gif"

if image_url is None:
    print("No image found for latest outlook")
    exit()

# Download the image
r = requests.get(image_url)
with open(filename, "wb") as f:
    f.write(r.content)

# Upload to GitHub Pages using REST API
with open(filename, "rb") as f:
    content_b64 = base64.b64encode(f.read()).decode()

api_url = f"https://api.github.com/repos/{REPO}/contents/{PAGE_FOLDER}/{filename}"

# Check if file already exists to get SHA
r = requests.get(api_url, headers={"Authorization": f"token {GH_TOKEN}"})
sha = r.json()["sha"] if r.status_code == 200 else None

payload = {
    "message": f"Update {filename}",
    "content": content_b64,
    "branch": BRANCH,
}
if sha:
    payload["sha"] = sha

r = requests.put(api_url, headers={"Authorization": f"token {GH_TOKEN}"}, data=json.dumps(payload))
if r.status_code not in [200, 201]:
    print("Error uploading to GitHub Pages:", r.text)
    exit()

# Construct public GitHub Pages URL
public_url = f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{PAGE_FOLDER}/{filename}"

# Post to Discord as an embed
data = {
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
requests.post(WEBHOOK_URL, json=data)

# Update state file
with open(STATE_FILE, "w") as f:
    f.write(latest.id)

# Clean up local file
os.remove(filename)

print("Posted SPC outlook to Discord successfully!")
