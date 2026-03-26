import feedparser
import requests
import json
import os

WEBHOOK_URL = os.environ["https://discord.com/api/webhooks/1486827605087748108/Oga9GPq_iALtvY4GXNFfBW-AdAysNnvUP-Hdp5dsVQ6MtNt9G0cxWayXY7E35TRmYroU"]
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
            "content": f"🚨 **New SPC Outlook**\n{latest.title}\n{latest.link}"
        }

        requests.post(WEBHOOK_URL, json=data)

        with open(STATE_FILE, "w") as f:
            f.write(latest.id)
