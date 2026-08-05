import requests
import json
import time

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]

REPO = "arval-o/Discord-Weather-Minion"
BRANCH = "main"
PAGE_FOLDER = "docs"

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
