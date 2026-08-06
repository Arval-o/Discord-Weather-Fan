import os
import requests
import math
import nexradaws
import pyart
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from datetime import datetime
import tempfile
from shapely.geometry import shape

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
    # AWS organizes by year, month, day
    scans = conn.get_avail_scans(now.year, "{:02d}".format(now.month), "{:02d}".format(now.day), radar_id)
    if not scans:
        return None
    latest_scan = scans[-1]

    temp_dir = tempfile.mkdtemp()
    results = conn.download([latest_scan], temp_dir)
    if results.success:
        return results.success[0].filepath
    return None

def generate_radar_image(storm_props, storm_geom, output_path="radar_output.png"):
    # 1. Calculate Storm Center
    storm_shape = shape(storm_geom)
    center = storm_shape.centroid
    lat, lon = center.y, center.x

    # 2. Fetch Data
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

    # 3. Setup Plot
    prob_tor = int(storm_props.get("ProbTor", 0))
    prob_hail = int(storm_props.get("ProbHail", 0))

    fig = plt.figure(figsize=(12, 10))
    display = pyart.graph.RadarMapDisplay(radar)

    # Bounding boxes
    micro_bounds = [lon - 0.3, lon + 0.3, lat - 0.3, lat + 0.3]
    macro_bounds = [lon - 1.0, lon + 1.0, lat - 1.0, lat + 1.0]

    # Reflectivity and street map
    ax1 = fig.add_subplot(221, projection=ccrs.PlateCarree())
    display.plot_ppi_map('reflectivity', 0, vmin=-8, vmax=64, ax=ax1,
                         cmap=pyart.graph.cm.NWSRef,
                         title=f"{radar_id} Base Reflectivity & Path",
                         min_lon=macro_bounds[0], max_lon=macro_bounds[1],
                         min_lat=macro_bounds[2], max_lat=macro_bounds[3],
                         resolution='50m', fig=fig, alpha=0.6)

    # Storm polygon
    if storm_geom.get('type') == 'Polygon':
        coords = storm_geom['coordinates'][0]
        x = [c[0] for c in coords]
        y = [c[1] for c in coords]
        ax1.plot(x, y, color='magenta', linewidth=3, transform=ccrs.PlateCarree())

        # Arrow
        me = float(storm_props.get("MOTION_EAST", 0)) / 60.0
        ms = float(storm_props.get("MOTION_SOUTH", 0)) / 60.0
        ax1.plot([lon, lon + me], [lat, lat - ms], color='black', linewidth=4, transform=ccrs.PlateCarree(), zorder=10)

    # Reflectivity (zoomed in)
    ax2 = fig.add_subplot(222, projection=ccrs.PlateCarree())
    display.plot_ppi_map('reflectivity', 0, vmin=-8, vmax=64, ax=ax2,
                         cmap=pyart.graph.cm.NWSRef, title="Core Reflectivity",
                         min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                         min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig)

    # Velocity
    ax3 = fig.add_subplot(223, projection=ccrs.PlateCarree())
    display.plot_ppi_map('velocity', 1, vmin=-40, vmax=40, ax=ax3,
                         cmap=pyart.graph.cm.NWSVel, title="Core Velocity",
                         min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                         min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig)

    # Dynamic panel
    ax4 = fig.add_subplot(224, projection=ccrs.PlateCarree())

    if prob_tor >= 15:
        # Tornado -> Spectrum Width (Turbulence/Rotation)
        display.plot_ppi_map('spectrum_width', 1, vmin=0, vmax=15, ax=ax4,
                             cmap=pyart.graph.cm.NWS_SPW, title="Spectrum Width (Rotation/Debris)",
                             min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                             min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig)
    elif prob_hail >= 30:
        # CC
        try:
            display.plot_ppi_map('cross_correlation_ratio', 0, vmin=0.8, vmax=1.05, ax=ax4,
                                 cmap='pyart_RefDiff', title="Correlation Coefficient (Hail)",
                                 min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                                 min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig)
        except:
            # Fallback if CC not available on this radar
            display.plot_ppi_map('reflectivity', 1, vmin=-8, vmax=64, ax=ax4, cmap=pyart.graph.cm.NWSRef, title="Mid-Level Reflectivity", min_lon=micro_bounds[0], max_lon=micro_bounds[1], min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig)
    else:
        # Wind -> Mid-Level Velocity
        display.plot_ppi_map('velocity', 2, vmin=-40, vmax=40, ax=ax4,
                             cmap=pyart.graph.cm.NWSVel, title="Mid-Level Velocity (Wind)",
                             min_lon=micro_bounds[0], max_lon=micro_bounds[1],
                             min_lat=micro_bounds[2], max_lat=micro_bounds[3], resolution='50m', fig=fig)

    # Cleanup memory and file
    plt.tight_layout()
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    try: os.remove(file_path)
    except: pass

    return output_path
