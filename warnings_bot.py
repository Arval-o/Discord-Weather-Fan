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

    def is_pds(props):
        text = " ".join([
            props.get("headline") or "",
            props.get("description") or "",
            props.get("instruction") or ""
        ]).lower()
    
        return "particularly dangerous situation" in text

    # --- Clean text safely ---
    headline = props.get("headline") or event
    description = " ".join((props.get("description") or "No description available.").split())[:2500]
    instruction = " ".join((props.get("instruction") or "No instructions provided.").split())[:1200]
    severity = props.get("severity") or "Unknown"

    event_lower = event.lower()

    pds = is_pds(props)

    # default fallback
    color = 3447003
    emoji = "⚠️"
    ping_everyone = False
    pds_header = ""
    pds_footer = ""

    if pds:
        ping_everyone = True

        pds_header = "🚨 **THIS IS A PARTICULARLY DANGEROUS SITUATION!!!** 🚨\n\n"
    
        footer_text = f"ONCE AGAIN, THIS IS NOT A REGULAR {event.upper()}! AN ABNORMALLY SEVERE SITUATION FOR THIS AREA IS UNFOLDING!"
    
        if "tornado warning" in event_lower:
            footer_text += " TAKE COVER NOW!!!"
        elif "severe thunderstorm warning" in event_lower:
            footer_text += " TAKE COVER NOW!!!"
        elif "blizzard warning" in event_lower:
            footer_text += " TAKE COVER NOW!!!"
    
        pds_footer = f"\n\n🚨 **{footer_text}** 🚨"
    
    if "tornado warning" in event_lower:
        color = 0xFF00FF if pds else 16711680 
        emoji = "🌪️"
        ping_everyone = True
    
    elif "tornado watch" in event_lower:
        color = 0x8B0000 if pds else 0xF4C2C2 
        emoji = "🌪️"
        ping_role = True

    elif "severe thunderstorm warning" in event_lower:
        color = 0xFF0000 if pds else 16776960 
        emoji = "⛈️"
        ping_role = True
    
    # --- Severe Thunderstorm Watch (soft green-yellow) ---
    elif "severe thunderstorm watch" in event_lower:
        color = 0xB8860B if pds else 0xC9D96C  
        emoji = "⛅"
    
    # --- Blizzard Warning ---
    elif "blizzard warning" in event_lower:
        color = 0x000000 if pds else 0xFF8C00  
        emoji = "❄️"
        ping_everyone = True
    
    # --- Snow-related (general) ---
    elif "snow" in event_lower:
        color = 0xFFFFFF  # white
        emoji = "❄️"
    
    # --- Flood Warning ---
    elif "flood warning" in event_lower:
        color = 0xFFFF00 if pds else 0x006400  
        emoji = "🌊"
    
    # --- Flash Flood Warning ---
    elif "flash flood warning" in event_lower:
        color = 0xFFFF00 if pds else 65280  
        emoji = "🌊"
        ping_role = True
    
    # --- Advisory ---
    elif "advisory" in event_lower:
        color = 0x3498DB  # blue
        emoji = "ℹ️"

    # --- Ping logic ---
    if ping_everyone:
        content = f"@everyone {emoji} **{event}**"
    elif ping_role:
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
