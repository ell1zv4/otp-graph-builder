import os
import zipfile
import pandas as pd
from pyrosm import OSM
from pyproj import Geod

OSM_FILE = "euskalherria.osm.pbf"
GTFS_FILES = ["1130.zip", "1262.zip", "1267.zip"]
MAX_WARN = 150  # meters

geod = Geod(ellps="WGS84")


def load_stops(gtfs_zip):
    with zipfile.ZipFile(gtfs_zip) as z:
        with z.open("stops.txt") as f:
            df = pd.read_csv(f)
            return df[["stop_id", "stop_name", "stop_lat", "stop_lon"]]


def nearest_road_distance(osm, lat, lon):
    # nearest node in OSM road network
    nodes = osm.get_network(nodes=True, network_type="walking")

    coords = nodes[["lat", "lon"]].values

    min_dist = float("inf")

    for nlat, nlon in coords[::50]:  # sampling for speed
        _, _, dist = geod.inv(lon, lat, nlon, nlat)
        if dist < min_dist:
            min_dist = dist

    return min_dist


def main():
    print("📦 Loading OSM (pyrosm)...")
    osm = OSM(OSM_FILE)

    results = []

    for gtfs in GTFS_FILES:
        print(f"\n📍 Processing {gtfs}")
        stops = load_stops(gtfs)

        for _, row in stops.iterrows():
            lat = row["stop_lat"]
            lon = row["stop_lon"]

            try:
                dist = nearest_road_distance(osm, lat, lon)

                results.append({
                    "gtfs": gtfs,
                    "stop": row["stop_name"],
                    "lat": lat,
                    "lon": lon,
                    "distance_m": dist
                })

            except Exception:
                results.append({
                    "gtfs": gtfs,
                    "stop": row["stop_name"],
                    "lat": lat,
                    "lon": lon,
                    "distance_m": 9999
                })

    df = pd.DataFrame(results)

    print("\n======================")
    print("🔥 WORST OFFENDERS")
    print("======================")

    worst = df.sort_values("distance_m", ascending=False).head(30)

    for _, r in worst.iterrows():
        print(f"{r['gtfs']} | {r['stop']}")
        print(f"   📍 {r['lat']}, {r['lon']}")
        print(f"   🚨 {r['distance_m']:.2f} m\n")

    bad = df[df["distance_m"] > MAX_WARN]

    print("\n======================")
    print(f"⚠️ BAD STOPS > {MAX_WARN}m: {len(bad)}")
    print("======================")


if __name__ == "__main__":
    main()
