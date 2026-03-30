import feedparser
import requests
import os
import json
import time
import base64
from shapely.geometry import shape, Point, box
from shapely.ops import nearest_points
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

# Risk order — used for all comparisons (avoids color-collision bugs)
RISK_ORDER = ["NONE", "TSTM", "MRGL", "SLGT", "ENH", "MDT", "HIGH"]

# The SPC GeoJSON LABEL2 field uses these exact strings for each category.
# "General Thunder" maps to TSTM; the severe categories use their short codes.
LABEL2_TO_RISK = {
    "TSTM":            "TSTM",   # older/alt spelling sometimes present
    "General Thunder": "TSTM",
    "Marginal":        "MRGL",
    "Slight":          "SLGT",
    "Enhanced":        "ENH",
    "Moderate":        "MDT",
    "High":            "HIGH",
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

    return f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/{PAGE_FOLDER}/{filename}?t={int(time.time())}"

# === RISK FUNCTION ===
# The SPC GeoJSON endpoints are:
#   Day 1 categorical: day1otlk_cat.lyr.geojson  (always current, no time suffix needed)
#   Day 2 categorical: day2otlk_cat.lyr.geojson
#   Day 3 categorical: day3otlk_cat.lyr.geojson
#
# The property for the risk label is LABEL2, with values like:
#   "General Thunder", "Marginal", "Slight", "Enhanced", "Moderate", "High"
#
# Polygons are "cake-layer" style: a point under MRGL also has a TSTM polygon
# covering it. We take the highest category found at the point.
#
# Probabilistic sub-risks (tornado/wind/hail %) use time-suffixed files, e.g.:
#   day1otlk_1300_torn.lyr.geojson

def parse_label2(label2_value):
    """Convert a LABEL2 string to our internal RISK_ORDER key."""
    if not label2_value:
        return "NONE"
    v = label2_value.strip()
    return LABEL2_TO_RISK.get(v, "NONE")

def get_risk(day, tag, point):
    """
    day  : int  (1, 2, or 3)
    tag  : str  issuance time tag for Day 1 (e.g. "1300"); None for Day 2/3
    point: shapely Point (lon, lat)

    Returns: (risk_str, sub_dict, nearest_tuple_or_None, found_list)
    """
    # --- Categorical GeoJSON ---
    cat_url = f"https://www.spc.noaa.gov/products/outlook/day{day}otlk_cat.lyr.geojson"
    try:
        cat_data = requests.get(cat_url, timeout=15).json()
    except Exception as e:
        print(f"Failed to fetch categorical GeoJSON (day {day}): {e}")
        return "NONE", {"tornado": 0, "wind": 0, "hail": 0, "sig": None}, None, []

    sample_box = box(point.x - SAMPLE_RADIUS, point.y - SAMPLE_RADIUS,
                     point.x + SAMPLE_RADIUS, point.y + SAMPLE_RADIUS)

    found = []
    for f in cat_data.get("features", []):
        try:
            geom = shape(f["geometry"])
            if geom.intersects(sample_box):
                risk_key = parse_label2(f["properties"].get("LABEL2", ""))
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
    if day == 1 and tag:
        prob_types = {
            "tornado": f"day1otlk_{tag}_torn.lyr.geojson",
            "wind":    f"day1otlk_{tag}_wind.lyr.geojson",
            "hail":    f"day1otlk_{tag}_hail.lyr.geojson",
        }
        for prob_key, prob_file in prob_types.items():
            try:
                prob_url = f"https://www.spc.noaa.gov/products/outlook/{prob_file}"
                prob_data = requests.get(prob_url, timeout=15).json()
                for f in prob_data.get("features", []):
                    try:
                        geom = shape(f["geometry"])
                        if geom.intersects(sample_box):
                            # LABEL2 for prob outlooks is e.g. "5%", "10%", "15%", "30%"
                            raw = f["properties"].get("LABEL2", "0%").replace("%", "").strip()
                            val = int(raw) if raw.isdigit() else 0
                            sub[prob_key] = max(sub[prob_key], val)
                            if f["properties"].get("sig"):
                                sub["sig"] = True
                    except Exception:
                        continue
            except Exception as e:
                print(f"Could not fetch {prob_file}: {e}")

    # --- Nearest higher risk polygon ---
    higher_candidates = []
    for f in cat_data.get("features", []):
        try:
            geom = shape(f["geometry"])
            cat = parse_label2(f["properties"].get("LABEL2", ""))
            if RISK_ORDER.index(cat) <= RISK_ORDER.index(risk):
                continue
            dist_deg = geom.exterior.distance(point)
            dist_miles = dist_deg * 69
            _, nearest_pt = nearest_points(point, geom.exterior)
            higher_candidates.append((cat, dist_miles, nearest_pt))
        except Exception:
            continue

    nearest = None
    if higher_candidates:
        higher_candidates.sort(key=lambda x: x[1])
        best = higher_candidates[0]
        dx = best[2].x - point.x
        dy = best[2].y - point.y
        angle = (degrees(atan2(dy, dx)) + 360) % 360
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        nearest = (best[0], int(best[1]), dirs[int((angle + 22.5) // 45) % 8])

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
        risk, sub, nearest, found = get_risk(1, tag, POINT)
        prev_risk = last_id.get("1_risk")
        trend = ""
        if prev_risk and prev_risk != risk:
            if RISK_ORDER.index(risk) > RISK_ORDER.index(prev_risk):
                trend = f"Risk: {risk} ⚠️ (up from {prev_risk})"
            else:
                trend = f"Risk: {risk} (down from {prev_risk})"
        else:
            trend = f"Risk: {risk}"

        # ping logic
        if risk in ["ENH", "MDT"]:
            content = f"<@&{ROLE_ID}>"
        elif risk == "HIGH":
            content = "@everyone"

        lines = [trend]
        tor, wind, hail, sig = sub["tornado"], sub["wind"], sub["hail"], sub["sig"]
        if tor or wind or hail:
            if tor: lines.append(f"Tornado: {tor}%")
            if wind: lines.append(f"Wind: {wind}%")
            if hail: lines.append(f"Hail: {hail}%")
        else:
            lines.append("No tornado, wind, or hail risk.")

        if nearest:
            lines.append(f"Nearest higher risk: {nearest[0]} (~{nearest[1]} mi {nearest[2]})")
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
            r2, sub2, nearest2, found2 = get_risk(2, None, POINT)
            r3, sub3, nearest3, found3 = get_risk(3, None, POINT)

            # trend messages — use RISK_ORDER for comparison, not colors
            prev_r2 = last_id.get("2_risk")
            trend2 = ""
            if prev_r2:
                if RISK_ORDER.index(r2) > RISK_ORDER.index(prev_r2):
                    trend2 = f"Risk: {r2} ⚠️ (up from {prev_r2})"
                elif RISK_ORDER.index(r2) < RISK_ORDER.index(prev_r2):
                    trend2 = f"Risk: {r2} (down from {prev_r2})"
                else:
                    trend2 = f"Risk: {r2}"
            else:
                trend2 = f"Risk: {r2}"

            prev_r3 = last_id.get("3_risk")
            trend3 = ""
            if prev_r3:
                if RISK_ORDER.index(r3) > RISK_ORDER.index(prev_r3):
                    trend3 = f"Risk: {r3} ⚠️ (up from {prev_r3})"
                elif RISK_ORDER.index(r3) < RISK_ORDER.index(prev_r3):
                    trend3 = f"Risk: {r3} (down from {prev_r3})"
                else:
                    trend3 = f"Risk: {r3}"
            else:
                trend3 = f"Risk: {r3}"

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
