import requests
import json
import time

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]

STATE_FILE = "state.json"
PROBSEVERE_URL = "https://mesonet.agron.iastate.edu/geojson/probsevere.geojson"

ROLE_ID = "1485401778962043021"
MY_ID = "1109224984984956968"

THRESHOLD_TOR = 15
THRESHOLD_WIND = 50
THRESHOLD_HAIL = 30

def fetch_probsevere():
    headers = {"User-Agent": "Discord-Weather-Minion"}
    try:
        r = requests.get(PROBSEVERE_URL, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error fetching ProbSevere: {e}")
        return None

def process_storms(data):
    features = data.get("features", [])
    print(f"Tracking {len(features)} storm objects nationwide...")

    for storm in features:
        props = storm.get("properties", {})
        storm_id = props.get("id", "Unknown")

        try:
            prob_tor = int(props.get("prob_tor", 0))
            prob_wind = int(props.get("prob_wind", 0))
            prob_hail = int(props.get("prob_hail", 0))
        except ValueError:
            continue

        if prob_tor >= THRESHOLD_TOR or prob_wind >= THRESHOLD_WIND or prob_hail >= THRESHOLD_HAIL:

            # ADD SHAPELY LOGIC HERE

            geom = storm.get("geometry", {})
            if geom.get("type") == "Polygon":
                # Just grabbing the first coordinate point for a quick printout
                lon, lat = geom["coordinates"][0][0]

            print(f"🚨 ALERT TRIGGERED: Storm ID {storm_id}")
            print(f"Location Approx: {lat}, {lon}")
            print(f"Tornado: {prob_tor}% | Wind: {prob_wind}% | Hail: {prob_hail}%")
            print(f"Moving: {props.get('motion_dir')}° at {props.get('motion_spd')} knots\n")

            # TODO: Post to webhook

def main():
    print("Checking ProbSevere V3 Output...")
    data = fetch_probsevere()

    if data:
        process_storms(data)

if __name__ == "__main__":
    main()
