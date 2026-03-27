import requests
import os
import json
import time

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
STATE_FILE = "last_warnings.txt"

URL = "https://api.weather.gov/alerts/active?area=PA"

TARGET_COUNTY = None
NWS_OFFICE = "PBZ"
TARGET_TYPES = ["Tornado Warning", "Severe Thunderstorm Warning"]

# Optional: put your role ID here (or leave None)
ROLE_ID = None  # Example: "123456789012345678"

# Load posted alerts
try:
    with open(STATE_FILE, "r") as f:
        posted_ids = set(f.read().splitlines())
except:
    posted_ids = set()

headers = {
    "User-Agent": "weather-bot (your-email@example.com)"
}

r = requests.get(URL, headers=headers)

if r.status_code != 200:
    print("Error fetching alerts")
    exit()

data = r.json()

new_ids = set(posted_ids)

for alert in data.get("features", []):
    props = alert["properties"]

    alert_id = props.get("id")
    event = props.get("event", "")
    area = props.get("areaDesc", "")

    # Filter by county + type
    sender = props.get("senderName", "")

    if NWS_OFFICE and "Pittsburgh" not in sender:
        continue
    
    if TARGET_COUNTY and TARGET_COUNTY not in area:
        continue

    if event not in TARGET_TYPES:
        print("No warnings of requested types")
        continue

    if alert_id in posted_ids:
        print("No alert_id")
        continue

    # Extract info
    headline = props.get("headline", event)
    description = props.get("description", "No description available.")
    instruction = props.get("instruction", "No instructions provided.")
    severity = props.get("severity", "Unknown")

    # Trim long text (Discord limit safety)
    description = description[:900]
    instruction = instruction[:300]

    # Color + emoji based on type
    if event == "Tornado Warning":
        color = 15158332  # red
        emoji = "🌪️"
    else:
        color = 16776960  # yellow
        emoji = "⛈️"

    # Role ping or everyone
    if ROLE_ID:
        content = f"<@&{ROLE_ID}> {emoji} **{event}**"
    else:
        content = f"@everyone {emoji} **{event}**"

    radar_url = f"https://radar.weather.gov/ridge/standard/KPBZ_loop.gif?t={int(time.time())}"
    embed = {
        "title": headline,
        "description": description,
        "color": color,
        "fields": [
            {"name": "Area", "value": area, "inline": False},
            {"name": "Severity", "value": severity, "inline": True},
            {"name": "Instructions", "value": instruction, "inline": False}
        ],
        "image": {
            "url": radar_url
        }
    }
    payload = {
        "content": content,
        "embeds": [embed]
    }

    response = requests.post(WEBHOOK_URL, json=payload)

    if response.status_code == 204:
        print(f"Posted: {event}")
        new_ids.add(alert_id)
    else:
        print("Discord error:", response.text)

# Save updated IDs
with open(STATE_FILE, "w") as f:
    f.write("\n".join(new_ids))
