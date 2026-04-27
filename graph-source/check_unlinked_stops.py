import os
import zipfile
import pandas as pd
import osmnx as ox
from shapely.geometry import Point
from pyproj import Geod

# CONFIG
OSM_FILE = "euskalherria.osm.pbf"
GTFS_FILES = ["1130.zip", "1262.zip", "1267.zip"]
MAX_WARN = 150  # metros

geod = Geod(ellps="WGS84")


def load_stops(gtfs_zip):
    with zipfile.ZipFile(gtfs_zip) as z:
        with z.open("stops.txt") as f:
            df = pd.read_csv(f)
            return df[["stop_id", "stop_name", "stop_lat", "stop_lon"]]


def distance_to_nearest_road(graph, lat, lon):
    node = ox.distance.nearest_nodes(graph, X=lon, Y=lat)
    node_lat = graph.nodes[node]["y"]
    node_lon = graph.nodes[node]["x"]

    _, _, dist = geod.inv(lon, lat, node_lon, node_lat)
    return dist


def main():
    print("📦 Loading OSM...")
    graph = ox.graph_from_file(OSM_FILE, simplify=True)

    all_results = []

    for gtfs in GTFS_FILES:
        print(f"\n📍 Processing {gtfs}")

        stops = load_stops(gtfs)

        for _, row in stops.iterrows():
            lat = row["stop_lat"]
            lon = row["stop_lon"]

            try:
                dist = distance_to_nearest_road(graph, lat, lon)

                all_results.append({
                    "gtfs": gtfs,
                    "stop_id": row["stop_id"],
                    "name": row["stop_name"],
                    "lat": lat,
                    "lon": lon,
                    "distance_m": dist
                })

            except Exception as e:
                all_results.append({
                    "gtfs": gtfs,
                    "stop_id": row["stop_id"],
                    "name": row["stop_name"],
                    "lat": lat,
                    "lon": lon,
                    "distance_m": 9999
                })

    df = pd.DataFrame(all_results)

    print("\n==============================")
    print("❌ WORST OFFENDING STOPS")
    print("==============================\n")

    worst = df.sort_values("distance_m", ascending=False).head(30)

    for _, r in worst.iterrows():
        print(f"{r['gtfs']} | {r['name']}")
        print(f"   📍 {r['lat']}, {r['lon']}")
        print(f"   🚨 distance: {r['distance_m']:.2f} m\n")

    print("\n==============================")
    print("📊 SUMMARY")
    print("==============================")
    print(df["distance_m"].describe())

    bad = df[df["distance_m"] > MAX_WARN]

    print(f"\n⚠️ Stops > {MAX_WARN}m: {len(bad)} / {len(df)}")

    if len(bad) > 0:
        print("\n🔥 Top worst:")
        print(bad.sort_values("distance_m", ascending=False).head(10))


if __name__ == "__main__":
    main()
