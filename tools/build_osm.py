"""Convierte los datos crudos de OpenStreetMap en:
  - basemap.bin + basemap.json  (calles, agua y parques para dibujar el mapa)
  - places.json                 (negocios y lugares cerca de las paradas)

Uso: py -I tools/build_osm.py <transit.json> <carpeta_raw> <carpeta_salida>
"""
import base64
import glob
import json
import math
import os
import struct
import sys

TRANSIT, RAW, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

with open(TRANSIT, encoding="utf-8") as f:
    t = json.load(f)
stops = [(la / 1e5, lo / 1e5) for la, lo in zip(t["stops"]["la"], t["stops"]["lo"])]
lats = [s[0] for s in stops]
lons = [s[1] for s in stops]
M = 0.035  # margen del mapa base
S, W, N, E = min(lats) - M, min(lons) - M, max(lats) + M, max(lons) + M

# --- índice de paradas para distancias rápidas ---
CELL = 0.01
grid = {}
for i, (la, lo) in enumerate(stops):
    grid.setdefault((int(la / CELL), int(lo / CELL)), []).append(i)


# celdas de 0.01° que quedan a unos 2 km de alguna parada (para filtrar calles residenciales rápido)
near_cells = set()
for la, lo in stops:
    cy, cx = int(la / CELL), int(lo / CELL)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            near_cells.add((cy + dy, cx + dx))


def near_any_stop(p):
    return (int(p[0] / CELL), int(p[1] / CELL)) in near_cells


def dist_m(a, b):
    kx = 111320 * math.cos(math.radians(a[0]))
    return math.hypot((a[1] - b[1]) * kx, (a[0] - b[0]) * 110540)


def nearest_stop(p, maxd):
    cy, cx = int(p[0] / CELL), int(p[1] / CELL)
    r = int(maxd / 1000 / CELL) + 1
    best = (1e18, -1)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            for i in grid.get((cy + dy, cx + dx), ()):
                d = dist_m(p, stops[i])
                if d < best[0]:
                    best = (d, i)
    return best


def simplify(pts, tol):
    n = len(pts)
    if n < 3:
        return pts
    kx = 111320 * math.cos(math.radians(pts[0][0]))
    xy = [(p[1] * kx, p[0] * 110540) for p in pts]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        ax, ay = xy[i]
        bx, by = xy[j]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        best, bi = -1.0, -1
        for k in range(i + 1, j):
            px, py = xy[k]
            if L == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                tt = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
                d = (px - ax - tt * dx) ** 2 + (py - ay - tt * dy) ** 2
            if d > best:
                best, bi = d, k
        if bi >= 0 and best > tol * tol:
            keep[bi] = True
            stack.append((i, bi))
            stack.append((bi, j))
    return [pts[i] for i in range(n) if keep[i]]


def q(p):
    x = round((p[1] - W) / (E - W) * 65535)
    y = round((p[0] - S) / (N - S) * 65535)
    return min(65535, max(0, x)), min(65535, max(0, y))


def inside(p):
    return S <= p[0] <= N and W <= p[1] <= E


CLASSES = ["park", "water", "river", "minor", "tertiary", "secondary", "primary", "trunk", "motorway"]
CI = {c: i for i, c in enumerate(CLASSES)}
HW = {
    "motorway": "motorway", "motorway_link": "motorway", "trunk": "trunk", "trunk_link": "trunk",
    "primary": "primary", "primary_link": "primary", "secondary": "secondary", "secondary_link": "secondary",
    "tertiary": "tertiary", "tertiary_link": "tertiary", "unclassified": "minor", "residential": "minor",
    "living_street": "minor",
}
names = []
name_idx = {}
records = []  # (class, name_id, [(x,y)...])


def name_id(n):
    if not n:
        return 0
    if n not in name_idx:
        names.append(n)
        name_idx[n] = len(names)
    return name_idx[n]


def add_line(cls, nm, pts, tol):
    run = []
    for p in pts + [None]:
        if p is not None and inside(p):
            run.append(p)
            continue
        if len(run) >= 2:
            sp = simplify(run, tol)
            qs = []
            for pp in sp:
                qq = q(pp)
                if not qs or qs[-1] != qq:
                    qs.append(qq)
            if len(qs) >= 2:
                records.append((CI[cls], name_id(nm), qs))
        run = []


def add_poly(cls, pts, tol):
    if len(pts) < 4:
        return
    if not any(inside(p) for p in pts):
        return
    sp = simplify(pts, tol)
    qs = []
    for pp in sp:
        qq = q(pp)
        if not qs or qs[-1] != qq:
            qs.append(qq)
    if len(qs) >= 3:
        records.append((CI[cls], 0, qs))


def geom(el):
    return [(g["lat"], g["lon"]) for g in el.get("geometry", []) if g]


def rings_from_relation(el):
    """Une los 'outer' de una multipolígono en anillos cerrados."""
    segs = [geom(m) for m in el.get("members", []) if m.get("type") == "way" and m.get("role", "outer") in ("outer", "") and m.get("geometry")]
    segs = [s for s in segs if len(s) >= 2]
    rings = []
    while segs:
        ring = segs.pop()
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += s[::-1][1:]
                elif s[-1] == ring[0]:
                    ring = s[:-1] + ring
                elif s[0] == ring[0]:
                    ring = s[::-1][:-1] + ring
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        rings.append(ring)
    return rings


# ---------- Naturaleza ----------
nat_path = os.path.join(RAW, "nature.json")
if os.path.exists(nat_path):
    with open(nat_path, encoding="utf-8") as f:
        nat = json.load(f)["elements"]
    for el in nat:
        tg = el.get("tags", {})
        if tg.get("waterway") in ("river", "canal") and el["type"] == "way":
            add_line("river", tg.get("name", ""), geom(el), 6)
            continue
        cls = "water" if tg.get("natural") == "water" else "park"
        if el["type"] == "way":
            g = geom(el)
            if len(g) >= 4 and g[0] == g[-1]:
                add_poly(cls, g, 6)
        elif el["type"] == "relation":
            for r in rings_from_relation(el):
                if len(r) >= 4:
                    add_poly(cls, r, 6)

# ---------- Calles ----------
seen = set()
road_count = {c: 0 for c in CLASSES}
for path in sorted(glob.glob(os.path.join(RAW, "roads_*.json"))):
    with open(path, encoding="utf-8") as f:
        els = json.load(f)["elements"]
    for el in els:
        if el["type"] != "way" or el["id"] in seen:
            continue
        seen.add(el["id"])
        tg = el.get("tags", {})
        cls = HW.get(tg.get("highway"))
        if not cls:
            continue
        g = geom(el)
        if len(g) < 2:
            continue
        if cls == "minor" and not (near_any_stop(g[len(g) // 2]) or near_any_stop(g[0]) or near_any_stop(g[-1])):
            continue
        nm = tg.get("name", "") or tg.get("ref", "")
        add_line(cls, nm, g, 2.5)
        road_count[cls] += 1

records.sort(key=lambda r: r[0])
buf = bytearray()
for cls, nid, qs in records:
    buf += struct.pack("<HHH", cls, nid, len(qs))
    for x, y in qs:
        buf += struct.pack("<HH", x, y)
os.makedirs(OUT, exist_ok=True)
# Los artifacts no sirven archivos binarios: la geometría va en base64 dentro del JSON.
with open(os.path.join(OUT, "basemap.json"), "w", encoding="utf-8") as f:
    json.dump({"bbox": [S, W, N, E], "classes": CLASSES, "names": names, "b64": base64.b64encode(bytes(buf)).decode("ascii")},
              f, ensure_ascii=False, separators=(",", ":"))
old_bin = os.path.join(OUT, "basemap.bin")
if os.path.exists(old_bin):
    os.remove(old_bin)

# ---------- Negocios ----------
CATS = {
    "super": "Supermercados", "tienda": "Tiendas", "conv": "Conveniencia", "farmacia": "Farmacias",
    "salud": "Salud", "comida": "Comida", "banco": "Bancos", "educacion": "Escuelas y bibliotecas",
    "gobierno": "Gobierno y servicios públicos", "gas": "Gasolineras", "diversion": "Diversión y parques",
    "hotel": "Hoteles", "servicios": "Servicios",
}
SERV_SHOPS = {"hairdresser", "beauty", "laundry", "dry_cleaning", "car_repair", "car", "tyres", "tattoo", "massage",
              "pawnbroker", "money_lender", "storage_rental", "copyshop", "nails", "cosmetics", "optician", "funeral_directors",
              "car_parts", "travel_agency", "rental", "insurance", "estate_agent", "vacant"}


def category(tg):
    a, s, tz, le = tg.get("amenity"), tg.get("shop"), tg.get("tourism"), tg.get("leisure")
    if s in ("supermarket", "wholesale", "greengrocer", "butcher", "grocery", "food"):
        return "super"
    if s in ("convenience", "kiosk", "alcohol", "tobacco"):
        return "conv"
    if s == "chemist" or a == "pharmacy":
        return "farmacia"
    if s in ("bakery", "pastry", "deli", "coffee", "confectionery"):
        return "comida"
    if s in SERV_SHOPS:
        return "servicios"
    if s == "vacant":
        return None
    if s:
        return "tienda"
    if a in ("hospital", "clinic", "doctors", "dentist"):
        return "salud"
    if a in ("restaurant", "fast_food", "cafe"):
        return "comida"
    if a == "bank":
        return "banco"
    if a in ("school", "college", "university", "library", "childcare"):
        return "educacion"
    if a in ("post_office", "townhall", "courthouse", "social_facility", "community_centre", "police", "fire_station") or tg.get("office") == "government":
        return "gobierno"
    if a == "fuel":
        return "gas"
    if a in ("cinema",) or tz in ("museum", "attraction", "zoo", "gallery", "theme_park") or le in ("park", "stadium", "sports_centre", "fitness_centre"):
        return "diversion"
    if tz in ("hotel", "motel"):
        return "hotel"
    if a in ("bus_station", "car_rental", "marketplace", "veterinary", "cinema"):
        return "servicios"
    return None


places = []
pl_path = os.path.join(RAW, "places.json")
if os.path.exists(pl_path):
    with open(pl_path, encoding="utf-8") as f:
        els = json.load(f)["elements"]
    seen_names = {}
    for el in els:
        tg = el.get("tags", {})
        nm = tg.get("name", "").strip()
        if not nm:
            continue
        if el["type"] == "node":
            p = (el["lat"], el["lon"])
        elif "center" in el:
            p = (el["center"]["lat"], el["center"]["lon"])
        else:
            continue
        cat = category(tg)
        if not cat:
            continue
        d, si = nearest_stop(p, 800)
        if d > 800:
            continue
        key = nm.lower()
        dup = False
        for q2 in seen_names.get(key, []):
            if dist_m(p, q2) < 80:
                dup = True
                break
        if dup:
            continue
        seen_names.setdefault(key, []).append(p)
        addr = " ".join(x for x in [tg.get("addr:housenumber", ""), tg.get("addr:street", "")] if x)
        places.append([nm, cat, round(p[0] * 1e5), round(p[1] * 1e5), tg.get("brand", ""), addr])

with open(os.path.join(OUT, "places.json"), "w", encoding="utf-8") as f:
    json.dump({"cats": CATS, "p": places}, f, ensure_ascii=False, separators=(",", ":"))

from collections import Counter
print(json.dumps({
    "records": len(records), "basemap_kb": len(buf) // 1024, "names": len(names), "roads": road_count,
    "places": len(places), "by_cat": Counter(p[1] for p in places),
    "walmart": sum(1 for p in places if "walmart" in (p[0] + p[4]).lower()),
    "places_kb": os.path.getsize(os.path.join(OUT, "places.json")) // 1024,
}, indent=1))
