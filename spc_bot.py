import feedparser
import requests
import os
import json
import time
import base64
from shapely.geometry import shape, Point, box, MultiPolygon
from shapely.ops import nearest_points, unary_union
from math import atan2, degrees

# === CONFIG ===
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]

REPO = "arval-o/Discord-Weather-Fan"
BRANCH = "main"
PAGE_FOLDER = "docs"
STATE_FILE = "last_id.txt"
RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"

ROLE_ID = "1485401778962043021"
MY_ID = "1109224984984956968"

# Your coordinate
POINT = Point(-80.096278, 40.615111)
SAMPLE_RADIUS = 0.008  # ~0.5 mi in degrees

PRIORITY_ORDER = ["2000", "1630", "1300", "0600", "0100"]

# Risk order — used for all comparisons
RISK_ORDER = ["NONE", "TSTM", "MRGL", "SLGT", "ENH", "MDT", "HIGH"]

# NOAA MapServer base URL
MAPSERVER = "https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/SPC_wx_outlks/MapServer"

# Layer IDs on the MapServer
# Day 1: Categorical=1, Prob Tornado=3, Prob Hail=5, Prob Wind=7
# Day 2: Categorical=9
# Day 3: Categorical=17
LAYER_IDS = {
    "cat":  {1: 1,  2: 9,  3: 17},
    "torn": {1: 3},
    "hail": {1: 5},
    "wind": {1: 7},
}

# The categorical `dn` integer → internal risk key
DN_TO_RISK = {
    2: "TSTM",
    3: "MRGL",
    4: "SLGT",
    5: "ENH",
    6: "MDT",
    8: "HIGH",
}

# Risk colors and emojis
RISK_COLORS = {
    "NONE": 0x808080,
    "TSTM": 0x90ee90,
    "MRGL": 0x006400,
    "SLGT": 0xFFFF00,
    "ENH": 0xFFA500,
    "MDT": 0xFF0000,
    "HIGH": 0xFF0000
}

RISK_EMOJIS = {
    "NONE": "⬜",
    "TSTM": "🟦",
    "MRGL": "🟩",
    "SLGT": "🟨",
    "ENH": "🟧",
    "MDT": "🟥",
    "HIGH": "⚠️"
}

# === LOAD STATE ===
try:
    with open(STATE_FILE, "r") as f:
        last_id = json.load(f)
except:
    last_id = {}

# === FETCH RSS ===
feed = feedparser.parse(RSS_URL)
entries = feed.entries[::-1]

# === DAY 1 COLLECTION ===
day1_all = []
for entry in entries:
    t = entry.title.lower()
    if "day 1" in t:
        for tag in PRIORITY_ORDER:
            if tag in t:
                day1_all.append((tag, entry))
day1_all.sort(key=lambda x: PRIORITY_ORDER.index(x[0]))

day1_to_post = None
last_priority = last_id.get("1_priority")
for tag, entry in day1_all:
    if entry.id == last_id.get("1"):
        continue
    if last_priority and PRIORITY_ORDER.index(tag) > PRIORITY_ORDER.index(last_priority):
        continue
    day1_to_post = (entry, tag)
    break

# === DAY 2/3 COLLECTION ===
day2 = None
day3 = None
for entry in entries:
    t = entry.title.lower()
    if "day 2" in t and not day2:
        day2 = entry
    elif "day 3" in t and not day3:
        day3 = entry

# === IMAGE UPLOAD ===
def upload_image(filename):
    img_response = requests.get(f"https://www.spc.noaa.gov/products/outlook/{filename}")
    if img_response.status_code != 200:
        print(f"Image fetch failed for {filename}: HTTP {img_response.status_code}")
        return None

    with open(filename, "wb") as img_file:
        img_file.write(img_response.content)

    api = f"https://api.github.com/repos/{REPO}/contents/{PAGE_FOLDER}/{filename}"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    check_response = requests.get(api, headers=headers)
    sha = check_response.json().get("sha") if check_response.status_code == 200 else None

    with open(filename, "rb") as img_file:
        content_b64 = base64.b64encode(img_file.read()).decode()

    payload = {"message": f"update {filename}", "content": content_b64, "branch": BRANCH}
    if sha:
        payload["sha"] = sha

    put_response = requests.put(api, headers=headers, data=json.dumps(payload))
    os.remove(filename)

    if put_response.status_code not in (200, 201):
        print(f"GitHub upload failed for {filename}: {put_response.text}")
        return None

    # GitHub Pages serves the docs/ folder as the site root, so the URL
    # does NOT include the PAGE_FOLDER segment — just /filename directly.
    user, repo_name = REPO.split("/")
    return f"https://{user}.github.io/{repo_name}/{filename}?t={int(time.time())}"

# === MAPSERVER QUERY ===
def query_layer(layer_id):
    """
    Query a NOAA MapServer layer and return its GeoJSON features.
    """
    url = f"{MAPSERVER}/{layer_id}/query"
    params = {
        "where": "1=1",
        "outFields": "*",
        "f": "geojson",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("features", [])
    except Exception as e:
        print(f"MapServer query failed for layer {layer_id}: {e}")
        return []

def geom_boundary(geom):
    """
    Return the exterior boundary of a geometry, handling both Polygon
    and MultiPolygon so that distance/nearest_points never fails.
    """
    if isinstance(geom, MultiPolygon):
        return unary_union([p.exterior for p in geom.geoms])
    return geom.exterior

# === RISK FUNCTION ===
def get_risk(day, point):
    """
    day  : int  (1, 2, or 3)
    point: shapely Point (lon, lat)

    Returns: (risk_str, sub_dict, nearest_tuple_or_None, found_list)
    """
    sample_box = box(point.x - SAMPLE_RADIUS, point.y - SAMPLE_RADIUS,
                     point.x + SAMPLE_RADIUS, point.y + SAMPLE_RADIUS)

    cat_features = query_layer(LAYER_IDS["cat"][day])

    found = []
    for f in cat_features:
        try:
            geom = shape(f["geometry"])
            if geom.intersects(sample_box):
                dn = f["properties"].get("dn")
                risk_key = DN_TO_RISK.get(dn, "NONE")
                if risk_key != "NONE":
                    found.append(risk_key)
        except Exception:
            continue

    # Highest risk at point
    risk = "NONE"
    for r in reversed(RISK_ORDER):
        if r in found:
            risk = r
            break

    # --- Probabilistic sub-risks (Day 1 only) ---
    sub = {"tornado": 0, "wind": 0, "hail": 0, "sig": None}
    if day == 1:
        for prob_key, layer_map in [("tornado", LAYER_IDS["torn"]),
                                    ("hail",    LAYER_IDS["hail"]),
                                    ("wind",    LAYER_IDS["wind"])]:
            prob_features = query_layer(layer_map[1])
            for f in prob_features:
                try:
                    geom = shape(f["geometry"])
                    if geom.intersects(sample_box):
                        dn = f["properties"].get("dn", 0)
                        sub[prob_key] = max(sub[prob_key], int(dn) if dn else 0)
                        if int(dn or 0) >= 10:
                            sub["sig"] = True
                except Exception:
                    continue

    # --- Nearest higher risk polygon ---
    # SPC polygons are cake-layered (SLGT contains MRGL contains TSTM).
    # We want the *next* risk level above the user's current risk, not
    # just the closest polygon boundary regardless of level.
    # Strategy: find the closest polygon for each level above current risk,
    # then pick the lowest such level (i.e. the next step up).
    current_idx = RISK_ORDER.index(risk)
    
    # Build a dict: risk_level -> list of (dist_miles, nearest_pt)
    higher_by_level = {}
    for f in cat_features:
        try:
            geom = shape(f["geometry"])
            dn = f["properties"].get("dn")
            cat = DN_TO_RISK.get(dn, "NONE")
            cat_idx = RISK_ORDER.index(cat)
            if cat_idx <= current_idx:
                continue
            boundary = geom_boundary(geom)
            dist_miles = boundary.distance(point) * 69
            _, nearest_pt = nearest_points(point, boundary)
            if cat not in higher_by_level or dist_miles < higher_by_level[cat][0]:
                higher_by_level[cat] = (dist_miles, nearest_pt)
        except Exception:
            continue

    nearest = None
    if higher_by_level:
        for r in RISK_ORDER[current_idx + 1:]:
            if r in higher_by_level:
                dist_miles, nearest_pt = higher_by_level[r]
    
                # === FIXED BEARING CALCULATION ===
                dx = nearest_pt.x - point.x   # longitude (E/W)
                dy = nearest_pt.y - point.y   # latitude (N/S)
    
                # Convert math angle → compass bearing
                angle = (450 - degrees(atan2(dy, dx))) % 360
    
                dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
                direction = dirs[int((angle + 22.5) // 45) % 8]
    
                nearest = (r, int(dist_miles), direction)
                break

    return risk, sub, nearest, found

# === BUILD EMBEDS ===
embeds = []
content = ""

# Track what we intend to commit to state — only written on successful Discord POST
pending_state = {}

# --- DAY 1 ---
if day1_to_post:
    entry, tag = day1_to_post
    print(f"Prepared Day 1 {tag}")
    img = upload_image(f"day1otlk_{tag}.png")
    if img:
        risk, sub, nearest, found = get_risk(1, POINT)
        prev_risk = last_id.get("1_risk")
        trend = ""
        emoji = RISK_EMOJIS.get(risk, "")
        if prev_risk and prev_risk != risk:
            if RISK_ORDER.index(risk) > RISK_ORDER.index(prev_risk):
                trend = f"{emoji} Risk: {risk} ** (⚠️ UP FROM {prev_risk})**"
            else:
                trend = f"{emoji} Risk: {risk} (down from {prev_risk})"
        else:
            trend = f"{emoji} Risk: {risk}"

        # ping logic
        if risk in ["ENH", "MDT"]:
            content = f"<@&{ROLE_ID}>"
        elif risk == "HIGH":
            content = "@everyone"

        lines = [trend]
        tor, wind, hail, sig = sub["tornado"], sub["wind"], sub["hail"], sub["sig"]
        if tor or wind or hail:
            if tor: lines.append(f"🌪️ Tornado: {tor}%")
            if wind: lines.append(f"💨 Wind: {wind}%")
            if hail: lines.append(f"🧊 Hail: {hail}%")
        else:
            lines.append("No tornado, wind, or hail risk.")

        if nearest:
            nearest_emoji = RISK_EMOJIS.get(nearest[0], "")
            lines.append(f"Nearest higher risk: {nearest_emoji} {nearest[0]} (~{nearest[1]} mi {nearest[2]})")
        else:
            lines.append("No higher risk levels in CONUS.")

        embeds.append({
            "title": entry.title,
            "url": entry.link,
            "description": "\n".join(lines),
            "color": RISK_COLORS.get(risk, 0x808080),
            "image": {"url": img}
        })

        # Stage state updates — not applied until Discord confirms
        pending_state["1"] = entry.id
        pending_state["1_priority"] = tag
        pending_state["1_risk"] = risk

# --- DAY 2/3 ---
if day2 and day3:
    if day2.id != last_id.get("2") or day3.id != last_id.get("3"):
        print("Prepared Day 2/3")
        img2 = upload_image("day2otlk.png")
        img3 = upload_image("day3otlk.png")
        if img2 and img3:
            r2, sub2, nearest2, found2 = get_risk(2, POINT)
            r3, sub3, nearest3, found3 = get_risk(3, POINT)

            # trend messages — use RISK_ORDER for comparison, not colors
            prev_r2 = last_id.get("2_risk")
            emoji2 = RISK_EMOJIS.get(r2, "")
            trend2 = ""
            if prev_r2:
                if RISK_ORDER.index(r2) > RISK_ORDER.index(prev_r2):
                    trend2 = f"{emoji2} Risk: {r2} ** (⚠️ UP FROM {prev_r2})**"
                elif RISK_ORDER.index(r2) < RISK_ORDER.index(prev_r2):
                    trend2 = f"{emoji2} Risk: {r2} (down from {prev_r2})"
                else:
                    trend2 = f"{emoji2} Risk: {r2}"
            else:
                trend2 = f"{emoji2} Risk: {r2}"

            prev_r3 = last_id.get("3_risk")
            emoji3 = RISK_EMOJIS.get(r3, "")
            trend3 = ""
            if prev_r3:
                if RISK_ORDER.index(r3) > RISK_ORDER.index(prev_r3):
                    trend3 = f"{emoji3} Risk: {r3} ** (⚠️ UP FROM {prev_r3})**"
                elif RISK_ORDER.index(r3) < RISK_ORDER.index(prev_r3):
                    trend3 = f"{emoji3} Risk: {r3} (down from {prev_r3})"
                else:
                    trend3 = f"{emoji3} Risk: {r3}"
            else:
                trend3 = f"{emoji3} Risk: {r3}"

            if not content:
                if r2 in ["ENH", "MDT"]:
                    content = f"<@&{ROLE_ID}>"
                elif r2 == "HIGH":
                    content = "@everyone"

            embeds.append({
                "title": "SPC Day 2 Outlook",
                "url": day2.link,
                "description": trend2,
                "color": RISK_COLORS.get(r2, 0x808080),
                "thumbnail": {"url": img2}
            })
            embeds.append({
                "title": "SPC Day 3 Outlook",
                "url": day3.link,
                "description": trend3,
                "color": RISK_COLORS.get(r3, 0x808080),
                "thumbnail": {"url": img3}
            })

            # Stage state updates
            pending_state["2"] = day2.id
            pending_state["3"] = day3.id
            pending_state["2_risk"] = r2
            pending_state["3_risk"] = r3

# === SEND TO DISCORD ===
if embeds:
    final_content = f"<@{MY_ID}>"
    if content:
        final_content += f" {content}"
    discord_response = requests.post(WEBHOOK_URL, json={"content": final_content, "embeds": embeds})
    if discord_response.status_code == 204:
        # Only now apply all pending state updates and persist
        last_id.update(pending_state)
        with open(STATE_FILE, "w") as f:
            json.dump(last_id, f)
        print("Posted to Discord")
    else:
        print("Discord error:", discord_response.text)
        print("State NOT saved — will retry next run")
else:
    print("Nothing to post")
