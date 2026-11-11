"""Convierte el GTFS de Trinity Metro en un JSON compacto para la app.

Uso: py -I tools/build_gtfs.py <carpeta_gtfs_extraida> <carpeta_salida>
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)


def rows(name):
    p = os.path.join(SRC, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def tsec(s):
    h, m, x = s.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(x)


def hav(a, b):
    R = 6371000.0
    la1, lo1 = math.radians(a[0]), math.radians(a[1])
    la2, lo2 = math.radians(b[0]), math.radians(b[1])
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(d))


def enc_num(v):
    v = ~(v << 1) if v < 0 else (v << 1)
    out = []
    while v >= 0x20:
        out.append(chr((0x20 | (v & 0x1F)) + 63))
        v >>= 5
    out.append(chr(v + 63))
    return "".join(out)


def encode(pts):
    plat = plon = 0
    s = []
    for lat, lon in pts:
        a, b = round(lat * 1e5), round(lon * 1e5)
        s.append(enc_num(a - plat))
        s.append(enc_num(b - plon))
        plat, plon = a, b
    return "".join(s)


def simplify(pts, tol):
    n = len(pts)
    if n < 3:
        return list(range(n))
    kx = 111320 * math.cos(math.radians(pts[0][0]))
    ky = 110540
    xy = [(p[1] * kx, p[0] * ky) for p in pts]
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
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
                d = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d > best:
                best, bi = d, k
        if bi >= 0 and best > tol * tol:
            keep[bi] = True
            stack.append((i, bi))
            stack.append((bi, j))
    return [i for i in range(n) if keep[i]]


def project(pts, cum, p, start_dist):
    """Distancia a lo largo de la forma del punto más cercano, sin retroceder."""
    kx = 111320 * math.cos(math.radians(p[0]))
    ky = 110540
    best = (1e18, start_dist)
    found_close = False
    for i in range(len(pts) - 1):
        if cum[i + 1] < start_dist:
            continue
        ax, ay = pts[i][1] * kx, pts[i][0] * ky
        bx, by = pts[i + 1][1] * kx, pts[i + 1][0] * ky
        px, py = p[1] * kx, p[0] * ky
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
        d = math.hypot(px - ax - t * dx, py - ay - t * dy)
        along = cum[i] + t * (cum[i + 1] - cum[i])
        if along < start_dist:
            along = start_dist
        if d < best[0]:
            best = (d, along)
        if d < 40:
            found_close = True
        elif found_close and d > 400:
            break
    return best[1]


# ---------- Agencias y rutas ----------
agencies = rows("agency.txt")
agency_idx = {a["agency_id"] or a["agency_name"]: i for i, a in enumerate(agencies)}

routes_raw = rows("routes.txt")


def route_sort_key(r):
    s = r["route_short_name"]
    rail = 0 if r["route_type"] in ("0", "1", "2") else 1
    num = int(s) if s.isdigit() else (int(s[:-1]) if s[:-1].isdigit() else 999)
    return (rail, num, s)


routes_raw.sort(key=route_sort_key)
route_idx = {r["route_id"]: i for i, r in enumerate(routes_raw)}
routes = []
for r in routes_raw:
    routes.append({
        "s": r["route_short_name"],
        "l": r["route_long_name"],
        "c": (r.get("route_color") or "555555").upper(),
        "t": (r.get("route_text_color") or "FFFFFF").upper(),
        "type": int(r["route_type"] or 3),
        "a": agency_idx.get(r.get("agency_id") or agencies[0]["agency_id"], 0),
        "u": r.get("route_url", ""),
    })

# ---------- Servicios ----------
cal = rows("calendar.txt")
cal_dates = rows("calendar_dates.txt")
services = sorted({c["service_id"] for c in cal} | {c["service_id"] for c in cal_dates})
svc_idx = {s: i for i, s in enumerate(services)}
days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
cal_out = []
for c in cal:
    mask = sum((1 << i) for i, d in enumerate(days) if c[d] == "1")
    cal_out.append([svc_idx[c["service_id"]], mask, int(c["start_date"]), int(c["end_date"])])
ex_out = [[svc_idx[c["service_id"]], int(c["date"]), int(c["exception_type"])] for c in cal_dates]

# ---------- Viajes y horarios ----------
trips = {t["trip_id"]: t for t in rows("trips.txt")}
st_by_trip = defaultdict(list)
dwell_count = 0
for r in rows("stop_times.txt"):
    if r["trip_id"] not in trips:
        continue
    arr = tsec(r["arrival_time"] or r["departure_time"])
    dep = tsec(r["departure_time"] or r["arrival_time"])
    if dep != arr:
        dwell_count += 1
    sdt = r.get("shape_dist_traveled", "")
    st_by_trip[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"], arr, dep, float(sdt) if sdt else None))

# ---------- Paradas usadas ----------
stops_raw = {s["stop_id"]: s for s in rows("stops.txt")}
used = set()
for lst in st_by_trip.values():
    for x in lst:
        used.add(x[1])
stop_ids = sorted(used, key=lambda s: (stops_raw[s]["stop_name"], s))
stop_idx = {s: i for i, s in enumerate(stop_ids)}
stops_out = {
    "n": [stops_raw[s]["stop_name"] for s in stop_ids],
    "d": [stops_raw[s].get("stop_desc", "") for s in stop_ids],
    "c": [stops_raw[s].get("stop_code", "") or s for s in stop_ids],
    "la": [round(float(stops_raw[s]["stop_lat"]) * 1e5) for s in stop_ids],
    "lo": [round(float(stops_raw[s]["stop_lon"]) * 1e5) for s in stop_ids],
}

# ---------- Formas ----------
shape_pts = defaultdict(list)
for r in rows("shapes.txt"):
    sdt = r.get("shape_dist_traveled", "")
    shape_pts[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lat"]), float(r["shape_pt_lon"]), float(sdt) if sdt else None))

shape_full = {}  # shape_id -> (pts, cum_m, agency_scale)
for sid, lst in shape_pts.items():
    lst.sort()
    pts = [(a, b) for _, a, b, _ in lst]
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + hav(pts[i - 1], pts[i]))
    ag = lst[-1][3]
    scale = (cum[-1] / ag) if ag else None
    shape_full[sid] = (pts, cum, scale)

shape_used = {}
shapes_out = []


def shape_index(sid):
    if sid in shape_used:
        return shape_used[sid]
    pts, cum, _ = shape_full[sid]
    keep = simplify(pts, 4.0)
    shapes_out.append({"p": encode([pts[i] for i in keep]), "d": [round(cum[i]) for i in keep]})
    shape_used[sid] = len(shapes_out) - 1
    return shape_used[sid]


# ---------- Patrones ----------
patterns = {}
pattern_list = []
projected = 0
for tid, lst in st_by_trip.items():
    lst.sort()
    t = trips[tid]
    sid = t.get("shape_id", "")
    if sid not in shape_full:
        continue
    pts, cum, scale = shape_full[sid]
    seq = tuple(stop_idx[x[1]] for x in lst)
    key = (route_idx[t["route_id"]], sid, seq, t.get("trip_headsign", ""), t.get("direction_id", "0"))
    if key not in patterns:
        sd = []
        prev = 0.0
        for k, x in enumerate(lst):
            if x[4] is not None and scale:
                d = x[4] * scale
            else:
                s = stops_raw[x[1]]
                d = project(pts, cum, (float(s["stop_lat"]), float(s["stop_lon"])), prev)
                projected += 1
            d = max(d, prev)
            sd.append(round(d))
            prev = d
        pat = {
            "r": key[0], "sh": shape_index(sid), "h": key[3], "dir": int(key[4] or 0),
            "s": list(seq), "sd": sd, "v": [], "w": [], "t": [], "_vk": {},
        }
        patterns[key] = pat
        pattern_list.append(pat)
    pat = patterns[key]
    start = lst[0][3]
    dep = tuple(x[3] - start for x in lst)
    dw = tuple(x[3] - x[2] for x in lst)
    vk = (dep, dw)
    if vk not in pat["_vk"]:
        pat["_vk"][vk] = len(pat["v"])
        pat["v"].append(list(dep))
        pat["w"].append(list(dw) if any(dw) else 0)
    pat["t"].append([svc_idx[t["service_id"]], start, pat["_vk"][vk]])

for p in pattern_list:
    del p["_vk"]
    p["t"].sort(key=lambda x: (x[1], x[0]))
    if not any(p["w"]):
        del p["w"]

fi = rows("feed_info.txt")
out = {
    "v": 1,
    "tz": agencies[0].get("agency_timezone", "America/Chicago"),
    "feed": fi[0] if fi else {},
    "agencies": [a["agency_name"] for a in agencies],
    "routes": routes,
    "stops": stops_out,
    "shapes": shapes_out,
    "patterns": pattern_list,
    "services": services,
    "cal": cal_out,
    "ex": ex_out,
}
path = os.path.join(OUT, "transit.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

lats = [x / 1e5 for x in stops_out["la"]]
lons = [x / 1e5 for x in stops_out["lo"]]
print(json.dumps({
    "routes": len(routes), "stops": len(stop_ids), "shapes": len(shapes_out),
    "patterns": len(pattern_list), "trips": sum(len(p["t"]) for p in pattern_list),
    "variants": sum(len(p["v"]) for p in pattern_list), "stop_times_with_dwell": dwell_count,
    "stops_projected": projected, "bytes": os.path.getsize(path),
    "bbox": [min(lats), min(lons), max(lats), max(lons)],
}, indent=1))
