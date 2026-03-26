import feedparser
import requests
import os

# Discord webhook from GitHub Secrets
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

# SPC RSS feed
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"

# File to track last posted outlook
STATE_FILE = "last_id.txt"

# Load last ID to avoid reposting
try:
    with open(STATE_FILE, "r") as f:
        last_id = f.read().strip()
except:
    last_id = ""

# Parse the RSS feed
feed = feedparser.parse(RSS_URL)

if feed.entries:
    latest = feed.entries[0]

    if latest.id != last_id:
        last_id = latest.id

        # Determine which image to post
        title = latest.title.lower()
        image_url = None

        if "day 1" in title:
            image_url = f"https://www.spc.noaa.gov/products/outlook/day1otlk.gif?{latest.id}"
        elif "day 2" in title:
            image_url = f"https://www.spc.noaa.gov/products/outlook/day2otlk.gif?{latest.id}"
        elif "day 3" in title:
            image_url = f"https://www.spc.noaa.gov/products/outlook/day3otlk.gif?{latest.id}"

        # Prepare the Discord embed
        data = {
            "embeds": [
                {
                    "title": latest.title,
                    "url": latest.link,
                    "description": "SPC Convective Outlook",
                    "image": {"url": image_url} if image_url else None,
                    "color": 16711680  # Red
                }
            ]
        }

        # Send to Discord
        requests.post(WEBHOOK_URL, json=data)

        # Update the state file
        with open(STATE_FILE, "w") as f:
            f.write(latest.id)
