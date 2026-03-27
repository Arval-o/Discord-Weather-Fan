import requests
import os
import json
import time

# === CONFIG ===
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
STATE_FILE = "last_warnings.txt"
URL = "https://api.weather.gov/alerts/active?area=PA"

TARGET_COUNTY = "Allegheny"
ROLE_ID = "1485401778962043021"  # Discord role for Severe Thunderstorm
MIN_LATITUDE = 40.55  # Optional: north of this latitude only

# === Load posted alerts ===
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

    # --- Optional: northern latitude filter ---
    geometry = alert.get("geometry")
    north_filter_pass = True
    if geometry and geometry.get("coordinates"):
        coords_list = []
        if geometry["type"] == "Polygon":
            coords_list = [pt for ring in geometry["coordinates"] for pt in ring]
        elif geometry["type"] == "MultiPolygon":
            coords_list = [pt for poly in geometry["coordinates"] for ring in poly for pt in ring]
        else:
            coords_list = [geometry["coordinates"]]

        # Pass if any coordinate is north of MIN_LATITUDE
        north_filter_pass = any(pt[1] >= MIN_LATITUDE for pt in coords_list)

    if not north_filter_pass:
        continue

    if alert_id in posted_ids:
        continue

    # --- Clean text safely ---
    headline = props.get("headline") or event
    description = " ".join((props.get("description") or "No description available.").split())[:800]
    instruction = " ".join((props.get("instruction") or "No instructions provided.").split())[:500]
    severity = props.get("severity") or "Unknown"

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

    # --- Ping logic ---
    if event == "Tornado Warning":
        content = f"@everyone {emoji} **{event}**"
    elif event == "Severe Thunderstorm Warning":
        if ROLE_ID:
            content = f"<@&{ROLE_ID}> {emoji} **{event}**"
        else:
            content = f"@here {emoji} **{event}**"
    else:
        content = f"{emoji} **{event}**"

    # --- Radar URL (auto-refresh) ---
    radar_url = f"https://radar.weather.gov/ridge/standard/KPBZ_loop.gif?t={int(time.time())}"

    # --- Build embed ---
    embed = {
        "title": headline,
        "description": description,
        "color": color,
        "fields": [
            {"name": "Area", "value": area, "inline": False},
            {"name": "Severity", "value": severity, "inline": True},
            {"name": "Instructions", "value": instruction, "inline": False},
            {"name": "Radar", "value": "[Open Radar](https://radar.weather.gov/station/kpbz/standard)", "inline": False}
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

# === Save posted IDs ===
with open(STATE_FILE, "w") as f:
    f.write("\n".join(new_ids))
