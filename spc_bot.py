import feedparser
import requests
import os

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"

feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries in RSS feed")
    exit()

latest = feed.entries[0]

# For testing, bypass last_id check
print("Posting:", latest.title)

# Determine image URL
title = latest.title.lower()
image_url = None
if "day 1" in title:
    image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk.gif"
elif "day 2" in title:
    image_url = "https://www.spc.noaa.gov/products/outlook/day2otlk.gif"
elif "day 3" in title:
    image_url = "https://www.spc.noaa.gov/products/outlook/day3otlk.gif"

if image_url:
    # Download image
    r = requests.get(image_url, stream=True)
    filename = image_url.split("/")[-1]
    with open(filename, "wb") as f:
        for chunk in r.iter_content(1024):
            f.write(chunk)

    # Post to Discord with file attachment
    with open(filename, "rb") as f:
        payload = {"content": f"🚨 {latest.title}\n{latest.link}"}
        requests.post(WEBHOOK_URL, data=payload, files={"file": f})

    os.remove(filename)

print("Done")
