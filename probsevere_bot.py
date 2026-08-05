import requests
import json
import re
import math
import time
from shapely.geometry import Point, shape, MultiPolygon
from shapely.affinity import translate

BASE_URL = "https://mrms.ncep.noaa.gov/ProbSevere/PROBSEVERE/"
STATE_FILE = "probsevere_state.json"

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
ROLE_ID = "1485401778962043021"
MY_ID = "1109224984984956968"

HOME_LAT = 40.615111
HOME_LON = -80.096278
HOME_POINT = Point(HOME_LON, HOME_LAT)

ALERT_BOX = HOME_POINT.buffer(0.25)

HOURS_TO_PROJECT = 1

THRESHOLD_TOR = 15
THRESHOLD_WIND = 40
THRESHOLD_HAIL = 20

def get_latest_probsevere_url():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(BASE_URL, headers=headers)
        r.raise_for_status()
        filenames = re.findall(r'href="(MRMS_PROBSEVERE_\d+_\d+\.json)"', r.text)
        if not filenames:
            return None
        return BASE_URL + filenames[-1]
    except Exception as e:
        print(f"Error finding latest data: {e}")
        return None

def fetch_probsevere():
    url = get_latest_probsevere_url()
    if not url:
        return None
    print(f"Downloading: {url}")
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error downloading data: {e}")
        return None

def post_to_discord(content):
    if WEBHOOK_URL == "YOUR_DISCORD_WEBHOOK_URL_HERE":
        print("Webhook URL not set! Please update the configuration.")
        return

    payload = {"content": content}
    try:
        requests.post(WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"Error posting to Discord: {e}")

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"alerted_storms": {}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def process_storms(data):
    features = data.get("features", [])
    print(f"Tracking {len(features)} storm objects nationwide...")

    state = load_state()
    current_time = time.time()

    # Clean up old storms from state (older than 2 hours)
    state["alerted_storms"] = {k: v for k, v in state["alerted_storms"].items()
                               if current_time - v.get("timestamp", 0) < 7200}

    for storm in features:
        props = storm.get("properties", {})
        storm_id = str(props.get("ID", "Unknown"))

        try:
            prob_tor = int(props.get("ProbTor", 0))
            prob_wind = int(props.get("ProbWind", 0))
            prob_hail = int(props.get("ProbHail", 0))
            motion_e = float(props.get("MOTION_EAST", 0))
            motion_s = float(props.get("MOTION_SOUTH", 0))
        except ValueError:
            continue

        if prob_tor >= THRESHOLD_TOR or prob_wind >= THRESHOLD_WIND or prob_hail >= THRESHOLD_HAIL:

            geom = storm.get("geometry", {})
            if not geom or geom.get("type") != "Polygon":
                continue

            current_footprint = shape(geom)
            current_center = current_footprint.centroid

            delta_lat = -(motion_s / 60.0) * HOURS_TO_PROJECT
            lat_radians = math.radians(current_center.y)
            delta_lon = ((motion_e / 60.0) / math.cos(lat_radians)) * HOURS_TO_PROJECT

            future_footprint = translate(current_footprint, xoff=delta_lon, yoff=delta_lat)
            swept_swath = MultiPolygon([current_footprint, future_footprint]).convex_hull
            final_threat_area = swept_swath.buffer(0.05)

            if final_threat_area.intersects(ALERT_BOX):

                previous_alert = state["alerted_storms"].get(storm_id)

                if not previous_alert or (prob_tor > previous_alert.get("prob_tor", 0) or
                                          prob_wind > previous_alert.get("prob_wind", 0)):

                    print(f"🚨 ALERT TRIGGERED: Storm ID {storm_id}")

                    message = f"<@&{ROLE_ID}> **SEVERE STORM APPROACHING!**\n"
                    message += f"**Tornado:** {prob_tor}%\n"
                    message += f"**Wind:** {prob_wind}%\n"
                    message += f"**Hail:** {prob_hail}% (Max Size: {props.get('MESH', '0')} in)\n"
                    message += f"This storm's projected path intersects our area!"

            post_to_discord(message)

            state["alerted_storms"][storm_id] = {
                        "timestamp": current_time,
                        "prob_tor": prob_tor,
                        "prob_wind": prob_wind
            }

    save_state(state)

def main():
    print("Starting ProbSevere Check...")
    data = fetch_probsevere()
    if data:
        process_storms(data)

if __name__ == "__main__":
    main()
