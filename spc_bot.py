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
        data = {
            "embeds": [
                {
                    "title": latest.title,
                    "url": latest.link,
                    "description": "SPC Convective Outlook",
                    "image": {
                        "url": "https://www.spc.noaa.gov/products/outlook/day1otlk_1300.gif"
                    },
                    "color": 16711680
                }
            ]
        }
        requests.post(WEBHOOK_URL, json=data)

        with open(STATE_FILE, "w") as f:
            f.write(latest.id)
