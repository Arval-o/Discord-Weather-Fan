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
        title = latest.title.lower()
        
        image_url = None
        
        if "day 1" in title:
            if "1300" in title:
                image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk_1300.gif"
            elif "1630" in title:
                image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk_1630.gif"
            elif "2000" in title:
                image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk_2000.gif"
        
        elif "day 2" in title:
            image_url = "https://www.spc.noaa.gov/products/outlook/day2otlk.gif"
        
        elif "day 3" in title:
            image_url = "https://www.spc.noaa.gov/products/outlook/day3otlk.gif"
        
        data = {
            "embeds": [
                {
                    "title": latest.title,
                    "url": latest.link,
                    "image": {"url": image_url} if image_url else {},
                    "color": 16711680
                }
            ]
        }
        requests.post(WEBHOOK_URL, json=data)

        with open(STATE_FILE, "w") as f:
            f.write(latest.id)
