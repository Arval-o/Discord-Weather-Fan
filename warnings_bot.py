import requests
import os
import json

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
STATE_FILE = "last_warnings.txt"

URL = "https://api.weather.gov/alerts/active?area=PA"

TARGET_COUNTY = "Allegheny"
KEYWORDS = ["Tornado Warning", "Severe Thunderstorm Warning"]

# Load already posted IDs
try:
    with open(STATE_FILE, "r") as f:
        posted_ids = set(f.read().splitlines())
except:
    posted_ids = set()

headers = {
    "User-Agent": "weather-bot (your-email@example.com)"
}

r = requests.get(URL, headers=headers)
data = r.json()

new_ids = set(posted_ids)

for alert in data["features"]:
    props = alert["properties"]
    
    alert_id = props["id"]
    event = props["event"]
    area = props["areaDesc"]

    # Filter warnings
    if TARGET_COUNTY in area and event in KEYWORDS:
        if alert_id in posted_ids:
            continue

        headline = props.get("headline", "Weather Alert")
        description = props.get("description", "")
        instruction = props.get("instruction", "")
        severity = props.get("severity", "Unknown")

        message = {
            "content": "@everyone **NEW WARNING**",
            "embeds": [
                {
                    "title": f"{event}",
                    "description": description[:1000],
                    "color": 15158332,
                    "fields": [
                        {"name": "Area", "value": area, "inline": False},
                        {"name": "Severity", "value": severity, "inline": True}
                    ]
                }
            ]
        }

        requests.post(WEBHOOK_URL, json=message)

        new_ids.add(alert_id)

# Save updated IDs
with open(STATE_FILE, "w") as f:
    f.write("\n".join(new_ids))
