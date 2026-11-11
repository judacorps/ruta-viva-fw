"""Descarga de OpenStreetMap (Overpass) las calles, agua, parques y negocios
del área de servicio de Trinity Metro.

Uso: py -I tools/fetch_osm.py <transit.json> <carpeta_salida_raw>
"""
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

TRANSIT, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
UA = "transit-map-builder/1.0"

with open(TRANSIT, encoding="utf-8") as f:
    t = json.load(f)
lats = [x / 1e5 for x in t["stops"]["la"]]
lons = [x / 1e5 for x in t["stops"]["lo"]]
M = 0.015
S, W, N, E = min(lats) - M, min(lons) - M, max(lats) + M, max(lons) + M
stops = list(zip(lats, lons))


def run(query, name):
    path = os.path.join(OUT, name)
    if os.path.exists(path) and os.path.getsize(path) > 100:
        print("ya existe", name, flush=True)
        return
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(6):
        ep = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
            json.loads(body)  # valida
            with open(path, "wb") as f:
                f.write(body)
            print(f"ok {name} {len(body)//1024} KB ({ep.split('/')[2]})", flush=True)
            time.sleep(2)
            return
        except Exception as e:  # noqa: BLE001
            wait = 10 * (attempt + 1)
            print(f"reintento {name}: {e} (espera {wait}s)", flush=True)
            time.sleep(wait)
    raise SystemExit(f"falló {name}")


ROADS = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"
STEP = 0.1
ny = math.ceil((N - S) / STEP)
nx = math.ceil((E - W) / STEP)
for iy in range(ny):
    for ix in range(nx):
        s, w = S + iy * STEP, W + ix * STEP
        n, e = min(N, s + STEP), min(E, w + STEP)
        if not any(s - 0.015 <= la <= n + 0.015 and w - 0.015 <= lo <= e + 0.015 for la, lo in stops):
            continue
        q = f'[out:json][timeout:180];way["highway"~"^({ROADS})$"]({s:.5f},{w:.5f},{n:.5f},{e:.5f});out tags geom;'
        run(q, f"roads_{iy}_{ix}.json")

bb = f"{S:.5f},{W:.5f},{N:.5f},{E:.5f}"
run(
    f'[out:json][timeout:240];(way["natural"="water"]({bb});relation["natural"="water"]({bb});'
    f'way["waterway"~"^(river|canal)$"]({bb});way["leisure"~"^(park|golf_course)$"]({bb});'
    f'relation["leisure"="park"]({bb}););out tags geom;',
    "nature.json",
)
AMEN = "pharmacy|hospital|clinic|doctors|dentist|bank|restaurant|fast_food|cafe|post_office|library|school|college|university|fuel|townhall|courthouse|social_facility|cinema|marketplace|community_centre|police|fire_station|bus_station|car_rental|childcare|veterinary"
run(
    f'[out:json][timeout:240];(nwr["shop"]["name"]({bb});nwr["amenity"~"^({AMEN})$"]["name"]({bb});'
    f'nwr["tourism"~"^(museum|attraction|zoo|hotel|motel|gallery|theme_park)$"]["name"]({bb});'
    f'nwr["leisure"~"^(park|stadium|sports_centre|fitness_centre)$"]["name"]({bb});'
    f'nwr["office"="government"]["name"]({bb}););out tags center;',
    "places.json",
)
print("bbox", bb)
