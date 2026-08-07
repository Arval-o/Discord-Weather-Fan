import os
import requests
import math
import nexradaws
import pyart
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.io.img_tiles as cimgt
from datetime import datetime
import tempfile
from shapely.geometry import shape

class GoogleRoadmap(cimgt.OSM):
    def _image_url(self, tile):
        x, y, z = tile
        return f'https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}'

def get_closest_radar(lat, lon):
    try:
        r = requests.get('https://api.weather.gov/radar/stations', timeout=10)
        stations = r.json()['features']
        closest = None
        min_dist = 9999
        for s in stations:
            geom = s.get('geometry')
            props = s.get('properties')
            if not geom or props.get('stationType') != 'WSR-88D':
                continue
            r_lon, r_lat = geom['coordinates']
            dist = math.hypot(r_lat - lat, r_lon - lon)
            if dist < min_dist:
                min_dist = dist
                closest = props['id']
        return closest
    except Exception as e:
        print(f"Error finding radar: {e}")
        return None

def download_latest_scan(radar_id):
    conn = nexradaws.NexradAwsInterface()
    now = datetime.utcnow()
    scans = conn.get_avail_scans(now.year, "{:02d}".format(now.month), "{:02d}".format(now.day), radar_id)
    if not scans:
        return None

    valid_scans = [s for s in scans if not s.filename.endswith('_MDM')]
    if not valid_scans:
        return None

    latest_scan = valid_scans[-1]

    temp_dir = tempfile.mkdtemp()
    results = conn.download([latest_scan], temp_dir)
    if results.success:
        return results.success[0].filepath
    return None

def generate_radar_image(storm_props, storm_geom, output_path="radar_output.png"):
    storm_shape = shape(storm_geom)
    center = storm_shape.centroid
    lat, lon = center.y, center.x

    radar_id = get_closest_radar(lat, lon)
    if not radar_id: return None
    print(f"Downloading {radar_id} radar for storm at {lat}, {lon}...")

    file_path = download_latest_scan(radar_id)
    if not file_path: return None

    try:
        radar = pyart.io.read(file_path)
    except Exception as e:
        print(f"Error reading radar file: {e}")
        return None

    prob_tor = int(storm_props.get("ProbTor", 0))
    prob_hail = int(storm_props.get("ProbHail", 0))

    fig = plt.figure(figsize=(12, 10))
    display = pyart.graph.RadarMapDisplay(radar)

    radar_proj = ccrs.LambertConformal(central_longitude=radar.longitude['data'][0], central_latitude=radar.latitude['data'][0])
    osm_tiles = GoogleRoadmap()

    motion_e = float(storm_props.get("MOTION_EAST", 0))
    motion_s = float(storm_props.get("MOTION_SOUTH", 0))
    speed_kts = math.hypot(motion_e, motion_s)

    lon_min, lon_max = lon - 1.0, lon + 1.0
    lat_min, lat_max = lat - 1.0, lat + 1.0

    # Camera shift threshold dropped to 5 knots!
    if speed_kts > 5:
        if motion_e > 0:   lon_min, lon_max = lon - 0.5, lon + 1.5
        elif motion_e < 0: lon_min, lon_max = lon - 1.5, lon + 0.5

        if motion_s > 0:   lat_min, lat_max = lat - 1.5, lat + 0.5
        elif motion_s < 0: lat_min, lat_max = lat - 0.5, lat + 1.5

    macro_bounds = [lon_min, lon_max, lat_min, lat_max]
    micro_bounds = [lon - 0.45, lon + 0.45, lat - 0.45, lat + 0.45]

    # --- PANEL 1: Macro Reflectivity ---
    ax1 = fig.add_subplot(221, projection=radar_proj)
    ax1.set_extent(macro_bounds, crs=ccrs.PlateCarree()) # Fix Cartopy Bug
    ax1.add_image(osm_tiles, 8)
    # vmin bumped to 10 to hide clear-air radar noise
    display.plot_ppi_map('reflectivity', 0, vmin=10, vmax=64, ax=ax1,
                         cmap='NWSRef',
                         title=f"{radar_id} Base Reflectivity & Path",
                         min_lon=macro_bounds[0], max_lon=macro_bounds[1],
                         min_lat=macro_bounds[2], max_lat=macro_bounds[3],
                         resolution='50m', fig=fig, alpha=0.7)

    if storm_geom.get('type') == 'Polygon':
        coords = storm_geom['coordinates'][0]
        x = [c[0] for c in coords]
        y = [c[1] for c in coords]
        ax1.plot(x, y, color='white', linewidth=3, transform=ccrs.PlateCarree())

        if speed_kts > 5: # Match the 5 knot threshold
            lat_radians = math.radians(lat)
            deg_lat_per_min = -(motion_s / 60.0) / 60.0
            deg_lon_per_min = (motion_e / 60.0) / math.cos(lat_radians) / 60.0

            dist_deg_per_min = math.hypot(deg_lon_per_min, deg_lat_per_min)
            fixed_length_deg = 0.5
            total_mins = fixed_length_deg / dist_deg_per_min

            end_lon = lon + (deg_lon_per_min * total_mins)
            end_lat = lat + (deg_lat_per_min * total_mins)
            ax1.plot([lon, end_lon], [lat, end_lat], color='white', linewidth=2, transform=ccrs.PlateCarree(), zorder=10)

            for frac in [0.33, 0.66, 1.0]:
                m_mins = total_mins * frac
                x_m = lon + (deg_lon_per_min * m_mins)
                y_m = lat + (deg_lat_per_min * m_mins)
                ax1.plot(x_m, y_m, marker='x', color='white', markersize=7, markeredgewidth=2, transform=ccrs.PlateCarree(), zorder=11)
                ax1.text(x_m, y_m + 0.02, f"{int(m_mins)}m", color='black', fontsize=9, fontweight='bold', transform=ccrs.PlateCarree(), zorder=12, bbox=dict(facecolor='white', alpha=0.5, edgecolor='none', pad=2))

        minx, miny = min(x), min(y)
        maxx, maxy = max(x), max(y)

    # --- PANEL 2: Micro Reflectivity ---
    ax2 = fig.add_subplot(222, projection=radar_proj)
    ax2.set_extent(micro_bounds, crs=ccrs.PlateCarree()) # Fix Cartopy Bug
    ax2.add_image(osm_tiles, 10)
    # vmin bumped to 10 to hide clear-air radar noise
    display.plot_ppi_map('reflectivity', 0, vmin=10, vmax=64, ax=ax2,
                         cmap='NWSRef', title="Core Reflectivity",
                         min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                         min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig, alpha=0.8)

    # --- PANEL 3: Micro Velocity ---
    ax3 = fig.add_subplot(223, projection=radar_proj)
    ax3.set_extent(micro_bounds, crs=ccrs.PlateCarree()) # Fix Cartopy Bug
    ax3.add_image(osm_tiles, 10)
    display.plot_ppi_map('velocity', 1, vmin=-40, vmax=40, ax=ax3,
                         cmap='NWSVel', title="Core Velocity",
                         min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                         min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig, alpha=0.8)

    # --- PANEL 4: Dynamic Threat ---
    ax4 = fig.add_subplot(224, projection=radar_proj)
    ax4.set_extent(micro_bounds, crs=ccrs.PlateCarree()) # Fix Cartopy Bug
    ax4.add_image(osm_tiles, 10)

    if prob_tor >= 15:
        display.plot_ppi_map('spectrum_width', 1, vmin=0, vmax=15, ax=ax4,
                             cmap='NWS_SPW', title="Spectrum Width (Rotation/Debris)",
                             min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                             min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig, alpha=0.8)
    elif prob_hail >= 30:
        try:
            display.plot_ppi_map('cross_correlation_ratio', 0, vmin=0.8, vmax=1.05, ax=ax4,
                                 cmap='RefDiff', title="Correlation Coefficient (Hail)",
                                 min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                                 min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig, alpha=0.8)
        except:
            display.plot_ppi_map('reflectivity', 1, vmin=10, vmax=64, ax=ax4, cmap='NWSRef', title="Mid-Level Reflectivity", min_lon=micro_bounds[0],max_lon=micro_bounds[1], min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig, alpha=0.8)
    else:
        display.plot_ppi_map('velocity', 1, vmin=-40, vmax=40, ax=ax4,
                             cmap='NWSVel', title="Mid-Level Velocity (Wind)",
                             min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                             min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig, alpha=0.8)

    if storm_geom.get('type') == 'Polygon':
        storm_id = storm_props.get("ID", "Unknown")
        for ax in [ax2, ax3, ax4]:
            ax.plot([minx, maxx, maxx, minx, minx], [miny, miny, maxy, maxy, miny], color='red', linewidth=3, transform=ccrs.PlateCarree(), zorder=10)
            ax.text(minx, maxy + 0.02, f"Storm Object {storm_id}", color='red', fontsize=10, fontweight='bold',
            transform=ccrs.PlateCarree(), zorder=12, bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=4))

    plt.tight_layout()
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    try: os.remove(file_path)
    except: pass

    return output_path
