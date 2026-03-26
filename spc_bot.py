import feedparser
import requests
import os

# Discord webhook from GitHub Secrets
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

# SPC RSS feed
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"

# File to store last posted outlook
STATE_FILE = "last_id.txt"

# Load last ID to prevent reposting
try:
    with open(STATE_FILE, "r") as f:
        last_id = f.read().strip()
except:
    last_id = ""

# Parse the RSS feed
feed = feedparser.parse(RSS_URL)

if feed.entries:
    latest = feed.entries[0]

    # Only post if this is a new outlook
    #if latest.id != last_id:
    last_id = latest.id

    title = latest.title.lower()
    image_url = None

    # Determine which SPC image to download
    if "day 1" in title:
        image_url = "https://www.spc.noaa.gov/products/outlook/day1otlk.gif"
    elif "day 2" in title:
        image_url = "https://www.spc.noaa.gov/products/outlook/day2otlk.gif"
    elif "day 3" in title:
        image_url = "https://www.spc.noaa.gov/products/outlook/day3otlk.gif"

    # If there is an image, download it
    if image_url:
        try:
            response = requests.get(image_url, stream=True)
            response.raise_for_status()

            filename = image_url.split("/")[-1]

            # Save temporary file
            with open(filename, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)

            # Send file to Discord
            with open(filename, "rb") as f:
                payload = {
                    "content": f"🚨 **{latest.title}**\n{latest.link}"
                }
                requests.post(WEBHOOK_URL, data=payload, files={"file": f})

            # Delete temporary file
            os.remove(filename)

        except Exception as e:
            print(f"Error downloading or sending image: {e}")

    # Update the last_id file
    with open(STATE_FILE, "w") as f:
        f.write(latest.id)
