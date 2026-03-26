import feedparser
import requests
import json
import os

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"
STATE_FILE = "last_id.txt"

# Load last ID
try:
    with open(STATE_FILE, "r") as f:
        last_id = f.read().strip()
except:
    last_id = ""

feed = feedparser.parse(RSS_URL)

if feed.entries:
    latest = feed.entries[0]

    if latest.id != last_id:
        last_id = latest.id
        title = latest.title.lower()

        if "day 1" in title:
            # Latest Day 1 outlook (convective outlook map)
            image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk.gif"
        elif "day 2" in title:
            image_url = "https://www.spc.noaa.gov/products/outlook/day2otlk.gif"
        elif "day 3" in title:
            image_url = "https://www.spc.noaa.gov/products/outlook/day3otlk.gif"
        else:
            image_url = None
        
        data = {
            "embeds": [
                {
                    "title": latest.title,
                    "url": latest.link,
                    "image": {"url": image_url} if image_url else None,
                    "color": 16711680
                }
            ]
        }
        requests.post(WEBHOOK_URL, json=data)

        with open(STATE_FILE, "w") as f:
            f.write(latest.id)
