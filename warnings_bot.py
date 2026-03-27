import requests
import os
import json
import time

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
STATE_FILE = "last_warnings.txt"

URL = "https://api.weather.gov/alerts/active?area=PA"

TARGET_COUNTY = "Allegheny"
ROLE_ID = "1485401778962043021"  # your Discord role
MIN_LATITUDE = 40.55  # roughly northern Allegheny County

# Load posted alerts
try:
    with open(STATE_FILE, "r") as f:
        posted_ids = set(f.read().splitlines())
except FileNotFoundError:
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

    # --- County filter ---
    if TARGET_COUNTY not in area:
        continue

    
    geometry = alert.get("geometry")
    north_filter_pass = True
    if geometry and geometry.get("coordinates"):
        # Take first coordinate (most warnings are polygons)
        coords = geometry["coordinates"][0][0] if geometry["type"] == "Polygon" else geometry["coordinates"]
        lat = coords[1] if isinstance(coords[0], list) else coords[1]
        if lat < MIN_LATITUDE:
            north_filter_pass = False
    if not north_filter_pass:
        continue

    if alert_id in posted_ids:
        continue

    # --- Clean up text ---
    headline = props.get("headline", event)
    description = " ".join(props.get("description", "No description available.").split())[:800]
    instruction = " ".join(props.get("instruction", "No instructions provided.").split())[:500]
    severity = props.get("severity", "Unknown")

    # --- Color + emoji ---
    if event == "Tornado Warning":
        color = 15158332  # red
        emoji = "🌪️"
    elif event == "Severe Thunderstorm Warning":
        color = 16776960  # yellow
        emoji = "⛈️"
    else:
        color = 3447003  # blue-ish for others
        emoji = "⚠️"

    # --- Decide who to ping ---
    if event == "Tornado Warning":
        content = f"@everyone {emoji} **{event}**"
    elif event == "Severe Thunderstorm Warning":
        content = f"<@&{ROLE_ID}> {emoji} **{event}**"
    else:
        content = f"{emoji} **{event}**"  # other warnings no ping

    # --- Radar ---
    radar_url = f"https://radar.weather.gov/ridge/standard/KPBZ_loop.gif?t={int(time.time())}"

    embed = {
        "title": headline,
        "description": description,
        "color": color,
        "fields": [
            {"name": "Area", "value": area, "inline": False},
            {"name": "Severity", "value": severity, "inline": True},
            {"name": "Instructions", "value": instruction, "inline": False},
            {"name": "Radar", "value": "[Open Radar](https://radar.weather.gov/region/east/standard)", "inline": False}
        ],
        "image": {"url": radar_url}
    }

    payload = {"content": content, "embeds": [embed]}
    response = requests.post(WEBHOOK_URL, json=payload)

    if response.status_code == 204:
        print(f"Posted: {event}")
        new_ids.add(alert_id)
    else:
        print("Discord error:", response.text)

# Save updated IDs
with open(STATE_FILE, "w") as f:
    f.write("\n".join(new_ids))
