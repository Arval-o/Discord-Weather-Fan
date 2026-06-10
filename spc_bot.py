import base64
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from math import atan2, degrees

import feedparser
import requests
from shapely.geometry import MultiPolygon, Point, box, shape
from shapely.ops import nearest_points, unary_union

# === CONFIG ===

WEBHOOK_URL = os.environ["WEBHOOK_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]

REPO = "arval-o/Discord-Weather-Fan"
BRANCH = "main"
PAGE_FOLDER = "docs"

STATE_FILE = "state.json"

RSS_URL = "https://www.spc.noaa.gov/products/spcacrss.xml"

ROLE_ID = "1485401778962043021"
MY_ID = "1109224984984956968"

# Anti-spam protection
POST_COOLDOWN_SECONDS = 60 * 60 * 3  # 3 hours

# Home location
HOME_LON = -80.096278
HOME_LAT = 40.615111

POINT = Point(HOME_LON, HOME_LAT)

# ~0.5 mile sampling radius
SAMPLE_RADIUS = 0.008

# Risk ranking
RISK_ORDER = [
    "NONE",
    "TSTM",
    "MRGL",
    "SLGT",
    "ENH",
    "MDT",
    "HIGH"
]

RISK_RANK = {
    risk: idx
    for idx, risk in enumerate(RISK_ORDER)
}

# NOAA MapServer base URL
MAPSERVER = (
    "https://mapservices.weather.noaa.gov/"
    "vector/rest/services/outlooks/SPC_wx_outlks/MapServer"
)

# Layer IDs
LAYER_IDS = {
    "cat": {
        1: 1,
        2: 9,
        3: 17
    },
    "torn": {
        1: 3
    },
    "hail": {
        1: 5
    },
    "wind": {
        1: 7
    }
}

# SPC categorical DN values
DN_TO_RISK = {
    2: "TSTM",
    3: "MRGL",
    4: "SLGT",
    5: "ENH",
    6: "MDT",
    8: "HIGH"
}

# Discord colors
RISK_COLORS = {
    "NONE": 0x808080,
    "TSTM": 0x90EE90,
    "MRGL": 0x006400,
    "SLGT": 0xFFFF00,
    "ENH": 0xFFA500,
    "MDT": 0xFF0000,
    "HIGH": 0x8B0000,
}

# Display emojis
RISK_EMOJIS = {
    "NONE": "⬜",
    "TSTM": "🟦",
    "MRGL": "🟩",
    "SLGT": "🟨",
    "ENH": "🟧",
    "MDT": "🟥",
    "HIGH": "⚠️",
}

DEFAULT_STATE = {
    "posted_day1": None,
    "posted_day2": None,
    "posted_day3": None,

    "waiting_day2": None,
    "waiting_day3": None,

    "last_day1_risk": None,
    "last_day2_risk": None,
    "last_day3_risk": None,

    "last_message_hash": "",
    "last_post_time": 0,

    "ping_date": "",
    "pinged_slgt": False,
    "pinged_enh": False,
    "pinged_mdt": False,
    "pinged_high": False,
}

# === STATE MANAGEMENT ===

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)

        # Ensure newly-added keys exist
        for key, value in DEFAULT_STATE.items():
            state.setdefault(key, value)

        return state

    except Exception as e:
        print(f"State load failed ({e}), creating fresh state")
        return DEFAULT_STATE.copy()


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


state = load_state()

# === DAILY PING RESET ===

today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

if state["ping_date"] != today:
    print("Resetting daily ping flags")

    state["ping_date"] = today

    state["pinged_slgt"] = False
    state["pinged_enh"] = False
    state["pinged_mdt"] = False
    state["pinged_high"] = False

    save_state(state)

# === FETCH RSS ===

feed = feedparser.parse(RSS_URL)

# Newest first
entries = list(reversed(feed.entries))

# === OUTLOOK COLLECTION ===

day1 = None
day2 = None
day3 = None

for entry in entries:
    title = entry.title.lower()

    if "day 1" in title and day1 is None:
        day1 = entry

    elif "day 2" in title and day2 is None:
        day2 = entry

    elif "day 3" in title and day3 is None:
        day3 = entry

# === OUTLOOK KEYS ===

def outlook_key(entry):
    """
    Stable identifier for outlook tracking.

    We intentionally avoid RSS GUIDs because SPC can
    occasionally republish entries.

    Title + link is stable enough for our purposes.
    """

    if not entry:
        return None

    raw = f"{entry.title}|{entry.link}"

    return hashlib.sha256(raw.encode()).hexdigest()


day1_key = outlook_key(day1)
day2_key = outlook_key(day2)
day3_key = outlook_key(day3)

# === NEW OUTLOOK DETECTION ===

day1_new = (
    day1_key is not None
    and day1_key != state["posted_day1"]
)

day2_new = (
    day2_key is not None
    and day2_key != state["posted_day2"]
)

day3_new = (
    day3_key is not None
    and day3_key != state["posted_day3"]
)

print("=== Outlook Status ===")
print(f"Day 1 new: {day1_new}")
print(f"Day 2 new: {day2_new}")
print(f"Day 3 new: {day3_new}")

print("=== State ===")
print(json.dumps(state, indent=2))

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
    current_rank = RISK_RANK[risk]
    
    # Build a dict: risk_level -> list of (dist_miles, nearest_pt)
    higher_by_level = {}
    for f in cat_features:
        try:
            geom = shape(f["geometry"])
            dn = f["properties"].get("dn")
            cat = DN_TO_RISK.get(dn, "NONE")
            cat_rank = RISK_RANK[cat]
            if cat_rank <= current_rank:
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
        for r in RISK_ORDER[current_rank + 1:]:
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
def risk_change(old_risk, new_risk):
    """
    Compare risks within the SAME forecast day.

    Returns:
        "upgrade"
        "downgrade"
        "same"
        None
    """

    if not old_risk:
        return None

    old_rank = RISK_RANK[old_risk]
    new_rank = RISK_RANK[new_risk]

    if new_rank > old_rank:
        return "upgrade"

    if new_rank < old_rank:
        return "downgrade"

    return "same"

# === DISCORD MESSAGE BUILDING ===

embeds = []

discord_content = ""

pending_state = {}

post_day1 = False
post_day23 = False

message_parts = []

def build_message_hash(parts):
    """
    Create a stable hash representing the
    exact outlooks being posted.
    """

    raw = json.dumps(parts, sort_keys=True)

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()

# helper functs


def should_ping_day1(state, risk, previous_risk):
    """
    Day 1:
    SLGT / ENH / MDT / HIGH once per day.
    After first ping, only upgrades.
    """

    change = risk_change(previous_risk, risk)

    if risk == "HIGH" and not state["pinged_high"]:
        return "@everyone"

    if risk == "MDT" and not state["pinged_mdt"]:
        return f"<@&{ROLE_ID}>"

    if risk == "ENH" and not state["pinged_enh"]:
        return f"<@&{ROLE_ID}>"

    if risk == "SLGT" and not state["pinged_slgt"]:
        return f"<@&{ROLE_ID}>"

    if change == "upgrade":

        if risk == "HIGH":
            return "@everyone"

        if risk in ["SLGT", "ENH", "MDT"]:
            return f"<@&{ROLE_ID}>"

    return None


def should_ping_day23(state, risk, previous_risk):
    """
    Day 2/3:
    ENH / MDT / HIGH only.
    """

    change = risk_change(previous_risk, risk)

    if risk == "HIGH" and not state["pinged_high"]:
        return "@everyone"

    if risk == "MDT" and not state["pinged_mdt"]:
        return f"<@&{ROLE_ID}>"

    if risk == "ENH" and not state["pinged_enh"]:
        return f"<@&{ROLE_ID}>"

    if change == "upgrade":

        if risk == "HIGH":
            return "@everyone"

        if risk in ["ENH", "MDT"]:
            return f"<@&{ROLE_ID}>"

    return None

# --- DAY 1 ---
if day1_new:
    entry = day1
    print(f"Prepared Day 1")
    img = upload_image("day1otlk.png")
    if img:
        risk, sub, nearest, found = get_risk(1, POINT)
        prev_risk = state.get("last_day1_risk")
        trend = ""
        emoji = RISK_EMOJIS.get(risk, "")
        if prev_risk and prev_risk != risk:
            if RISK_RANK[risk] > RISK_RANK[prev_risk]:
                trend = (
                    f"**{emoji} Risk: {risk}** "
                    f" **(⚠️ UP FROM {prev_risk})**\n"
                )
            else:
                trend = f"**{emoji} Risk: {risk}**\n"
        else:
            trend = f"**{emoji} Risk: {risk}**\n"

        # ping logic
        ping = None
        change_is_upgrade = (
            prev_risk
            and RISK_RANK[risk] > RISK_RANK[prev_risk]
        )
        if risk == "HIGH":

            if (
                not state["pinged_high"]
                or change_is_upgrade
            ):
                ping = "@everyone"
                pending_state["pinged_high"] = True
        elif risk == "MDT":
            if (
                not state["pinged_mdt"]
                or change_is_upgrade
            ):
                ping = f"<@&{ROLE_ID}>"
                pending_state["pinged_mdt"] = True
        elif risk == "ENH":
            if (
                not state["pinged_enh"]
                or change_is_upgrade
            ):
                ping = f"<@&{ROLE_ID}>"
                pending_state["pinged_enh"] = True
        elif risk == "SLGT":
            if (
                not state["pinged_slgt"]
                or change_is_upgrade
            ):
                ping = f"<@&{ROLE_ID}>"
                pending_state["pinged_slgt"] = True
        if ping and not discord_content:
            discord_content = ping
            
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
            lines.append(f"\n Nearest higher risk: {nearest_emoji} {nearest[0]} (~{nearest[1]} mi {nearest[2]})")
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
        pending_state["posted_day1"] = day1_key
        pending_state["last_day1_risk"] = risk

        message_parts.append(
            f"day1:{day1_key}"
        )
         
# --- DAY 2/3 ---
# --- DAY 2 / DAY 3 PAIRING LOGIC ---

day23_ready = False

if day2_new and day3_new:

    day23_ready = True

elif day2_new and not day3_new:

    print("Holding Day 2 until Day 3 updates")

    state["waiting_day2"] = day2_key

    save_state(state)

elif day3_new and not day2_new:

    print("Holding Day 3 until Day 2 updates")

    state["waiting_day3"] = day3_key

    save_state(state)

elif (
    state.get("waiting_day2") == day2_key
    and day3_new
):

    day23_ready = True

elif (
    state.get("waiting_day3") == day3_key
    and day2_new
):

    day23_ready = True


# --- DAY 2 / DAY 3 POSTING ---

if day23_ready:

    print("Prepared Day 2/3")


    img2 = upload_image("day2otlk.png")
    img3 = upload_image("day3otlk.png")

    if img2 and img3:

        r2, sub2, nearest2, found2 = get_risk(2, POINT)
        r3, sub3, nearest3, found3 = get_risk(3, POINT)

        # --------------------
        # Day 2 trend
        # --------------------

        prev_r2 = state.get("last_day2_risk")

        emoji2 = RISK_EMOJIS.get(r2, "")

        trend2 = ""

        if prev_r2:

            if RISK_RANK[r2] > RISK_RANK[prev_r2]:
                trend2 = (
                    f"{emoji2} Risk: {r2} "
                    f"** (⚠️ UP FROM {prev_r2})**"
                )

            elif RISK_RANK[r2] < RISK_RANK[prev_r2]:
                trend2 = (
                    f"{emoji2} Risk: {r2} "
                    f"(down from {prev_r2})"
                )

            else:
                trend2 = f"{emoji2} Risk: {r2}"

        else:

            trend2 = f"{emoji2} Risk: {r2}"

        # --------------------
        # Day 3 trend
        # --------------------

        prev_r3 = state.get("last_day3_risk")

        emoji3 = RISK_EMOJIS.get(r3, "")

        trend3 = ""

        if prev_r3:

            if RISK_RANK[r3] > RISK_RANK[prev_r3]:
                trend3 = (
                    f"{emoji3} Risk: {r3} "
                    f"** (⚠️ UP FROM {prev_r3})**"
                )

            elif RISK_RANK[r3] < RISK_RANK[prev_r3]:
                trend3 = (
                    f"{emoji3} Risk: {r3} "
                    f"(down from {prev_r3})"
                )

            else:
                trend3 = f"{emoji3} Risk: {r3}"

        else:

            trend3 = f"{emoji3} Risk: {r3}"

        # --------------------
        # Ping logic
        # --------------------

        highest_risk = max(
            [r2, r3],
            key=lambda r: RISK_RANK[r]
        )

        if not discord_content:
            upgrade = False
            
            if (
                prev_r2
                and RISK_RANK[r2] > RISK_RANK[prev_r2]
            ):
                upgrade = True
            
            if (
                prev_r3
                and RISK_RANK[r3] > RISK_RANK[prev_r3]
            ):
                upgrade = True

            if highest_risk == "HIGH":

                if (
                    not state["pinged_high"]
                    or upgrade
                ):
                    discord_content = "@everyone"
                    pending_state["pinged_high"] = True

            elif highest_risk == "MDT":

                if (
                    not state["pinged_mdt"]
                    or upgrade
                ):
                    discord_content = f"<@&{ROLE_ID}>"
                    pending_state["pinged_mdt"] = True

            elif highest_risk == "ENH":

                if (
                    not state["pinged_enh"]
                    or upgrade
                ):
                    discord_content = f"<@&{ROLE_ID}>"
                    pending_state["pinged_enh"] = True

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

        pending_state["posted_day2"] = day2_key
        pending_state["posted_day3"] = day3_key

        pending_state["waiting_day2"] = None
        pending_state["waiting_day3"] = None

        pending_state["last_day2_risk"] = r2
        pending_state["last_day3_risk"] = r3

        message_parts.append(f"day2:{day2_key}")
        message_parts.append(f"day3:{day3_key}")
        
if embeds:

    # Build duplicate-protection hash
    message_hash = build_message_hash(
        message_parts
    )

    now = int(time.time())

    if (
        message_hash == state.get("last_message_hash", "")
        and
        now - state.get("last_post_time", 0)
        < POST_COOLDOWN_SECONDS
    ):

        print(
            "Duplicate message blocked "
            "(hash + cooldown)"
        )

    else:

        final_content = f"<@{MY_ID}>"

        if discord_content:
            final_content += f" {discord_content}"

        discord_response = requests.post(
            WEBHOOK_URL,
            json={
                "content": final_content,
                "embeds": embeds
            },
            timeout=30
        )

        if discord_response.status_code == 204:

            # Anti-spam tracking
            pending_state["last_message_hash"] = (
                message_hash
            )

            pending_state["last_post_time"] = now

            # Apply all staged updates
            state.update(pending_state)

            save_state(state)

            print("Posted to Discord")
            

        else:

            print(
                "Discord error:",
                discord_response.text
            )

            print(
                "State NOT saved — "
                "will retry next run"
            )

else:

    print("Nothing to post")
    
