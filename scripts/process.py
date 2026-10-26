#!/usr/bin/env python3
"""Turn an Overpass export of Lyon into the compact data file used by the page.

Usage:
    python3 scripts/process.py export.json                 # writes data/lyon-data.json
    python3 scripts/process.py export.json --out other.json

The input is Overpass JSON (the "raw data" export, with an "elements" list) holding
Lyon's named streets as ways and its nine arrondissements as relations, both with
"out geom" geometry. See the README for the query. Standard library only.

Output format (all coordinates in metres from ORIGIN, x east, y north, delta-encoded
as flat [dx0, dy0, dx1, dy1, ...] integer lists):
    arr      {"1": [ring, ...], ...}       arrondissement outlines
    rivers   {"rhone": [line], "saone": [line]}
    streets  [[name, rank, arr_mask, length_m, [line, ...]], ...]
             rank: 0 trunk/primary, 1 secondary, 2 tertiary, 3 local, 4 pedestrian
             arr_mask: bit n set when the street lies in the n-th arrondissement
    osm      timestamp of the OpenStreetMap data
"""
import argparse
import collections
import json
import math
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

ORIGIN_LAT, ORIGIN_LON = 45.7578, 4.8320  # near Place Bellecour
KX = 111320 * math.cos(math.radians(ORIGIN_LAT))  # metres per degree of longitude
KY = 110574                                        # metres per degree of latitude

RANK = {"trunk": 0, "primary": 0, "secondary": 1, "tertiary": 2,
        "residential": 3, "unclassified": 3, "living_street": 3, "pedestrian": 4}

# Ramps, the tram line and technical links: not streets people learn.
SKIP_NAMES = re.compile(r"^(Trémie|Bretelle|T\d|Liaison |Voie Nouvelle |Autoroute )")

# Each river is drawn from the arrondissement borders that run down its middle.
# Borders between these pairs of arrondissements are river borders:
RIVER_BANKS = {"rhone": ({1, 2, 4}, {3, 6, 7}), "saone": ({5, 9}, {1, 2, 4})}
# Where the river is Lyon's outer edge there is no shared border, so these
# boundary ways (OSM way IDs) are added by hand. If OSM editors split or renumber
# them, the river loses that stretch: check the map after refreshing the data.
RIVER_EXTRA_WAYS = {"rhone": [451126788, 23841844, 38423089],
                    "saone": [439206248, 1346217932, 23842751, 23841848, 1346217920]}

# A street belongs to an arrondissement holding >= 15% of its length, or >= 150 m.
ARR_SHARE, ARR_MIN_M = 0.15, 150
STREET_SIMPLIFY_M, RING_SIMPLIFY_M = 2.5, 4


def proj(lon, lat):
    return ((lon - ORIGIN_LON) * KX, (lat - ORIGIN_LAT) * KY)


def stitch(segs):
    """Join open polylines that share end points into longer lines or closed rings."""
    segs = [s[:] for s in segs]
    rings = []
    while segs:
        ring = segs.pop(0)
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += s[::-1][1:]
                elif s[-1] == ring[0]:
                    ring = s + ring[1:]
                elif s[0] == ring[0]:
                    ring = s[::-1] + ring[1:]
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        rings.append(ring)
    return rings


def point_in_rings(pt, rings):
    x, y = pt
    inside = False
    for ring in rings:
        for i in range(len(ring) - 1):
            x1, y1 = ring[i]
            x2, y2 = ring[i + 1]
            if (y1 > y) != (y2 > y) and x1 + (y - y1) * (x2 - x1) / (y2 - y1) > x:
                inside = not inside
    return inside


def simplify(pts, eps):
    """Ramer-Douglas-Peucker line simplification, tolerance in metres."""
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    best, idx = -1, 0
    for i in range(1, len(pts) - 1):
        x0, y0 = pts[i]
        if length:
            dist = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / length
        else:
            dist = math.hypot(x0 - x1, y0 - y1)
        if dist > best:
            best, idx = dist, i
    if best > eps:
        return simplify(pts[: idx + 1], eps)[:-1] + simplify(pts[idx:], eps)
    return [pts[0], pts[-1]]


def delta_encode(pts):
    flat, px, py = [], 0, 0
    for x, y in pts:
        ix, iy = round(x), round(y)
        flat += [ix - px, iy - py]
        px, py = ix, iy
    return flat


def encode_rings(rings, eps):
    return [delta_encode(simplify(list(r), eps)) for r in rings]


def load_arrondissements(elements):
    """Return ({n: rings}, {way_id: set of arrondissements}, {way_id: lon/lat points})."""
    arr, owners, way_geom = {}, collections.defaultdict(set), {}
    for e in elements:
        if e["type"] != "relation":
            continue
        name = e["tags"]["name"]  # e.g. "Lyon 1er Arrondissement"
        n = int("".join(c for c in name.split("Lyon")[1] if c.isdigit()))
        outers = []
        for m in e["members"]:
            if m["type"] == "way" and m.get("role", "outer") in ("outer", "") and "geometry" in m:
                g = [(round(p["lon"], 7), round(p["lat"], 7)) for p in m["geometry"]]
                outers.append(g)
                owners[m["ref"]].add(n)
                way_geom[m["ref"]] = g
        rings = stitch(outers)
        if any(r[0] != r[-1] for r in rings):
            print("warning: unclosed boundary in", name, [len(r) for r in rings])
        arr[n] = [[proj(x, y) for x, y in r] for r in rings]
    return arr, owners, way_geom


def build_rivers(owners, way_geom):
    rivers = {k: [] for k in RIVER_BANKS}
    for ref, arrs in owners.items():
        if len(arrs) != 2:
            continue
        a, b = arrs
        for river, (west, east) in RIVER_BANKS.items():
            if (a in west and b in east) or (b in west and a in east):
                rivers[river].append([proj(x, y) for x, y in way_geom[ref]])
                break
    for river, refs in RIVER_EXTRA_WAYS.items():
        for ref in refs:
            if ref in way_geom:
                rivers[river].append([proj(x, y) for x, y in way_geom[ref]])
            else:
                print(f"warning: river way {ref} ({river}) not found in the export")
    return {k: stitch([[tuple(p) for p in s] for s in v]) for k, v in rivers.items()}


def build_streets(elements, arr):
    streets = {}
    for e in elements:
        if e["type"] != "way":
            continue
        tags = e["tags"]
        name = tags.get("name")
        if not name or SKIP_NAMES.match(name):
            continue
        name = name[0].upper() + name[1:]
        name = name.replace("Berges du Rhone", "Berges du Rhône")
        g = [proj(p["lon"], p["lat"]) for p in e["geometry"]]
        s = streets.setdefault(name, {"rank": 9, "lines": [], "len": 0.0,
                                      "arrlen": collections.Counter()})
        s["rank"] = min(s["rank"], RANK.get(tags.get("highway"), 3))
        s["lines"].append(g)
        for i in range(len(g) - 1):
            (x1, y1), (x2, y2) = g[i], g[i + 1]
            seg = math.hypot(x2 - x1, y2 - y1)
            s["len"] += seg
            mid = ((x1 + x2) / 2, (y1 + y2) / 2)
            for n, rings in arr.items():
                if point_in_rings(mid, rings):
                    s["arrlen"][n] += seg
                    break

    out, outside = [], 0
    for name, s in sorted(streets.items()):
        inside = sum(s["arrlen"].values())
        if inside < 1:  # the export can include a few streets just over the boundary
            outside += 1
            continue
        mask = 0
        for n, length in s["arrlen"].items():
            if length >= ARR_SHARE * inside or length >= ARR_MIN_M:
                mask |= 1 << n
        lines = [delta_encode(simplify(g, STREET_SIMPLIFY_M)) for g in s["lines"]]
        out.append([name, s["rank"], mask, round(s["len"]), lines])
    return out, outside


def main():
    ap = argparse.ArgumentParser(description="Turn an Overpass export of Lyon into data/lyon-data.json.")
    ap.add_argument("export", type=pathlib.Path, help="Overpass JSON export")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "data" / "lyon-data.json")
    args = ap.parse_args()

    raw = json.loads(args.export.read_text(encoding="utf-8"))
    elements = raw["elements"]

    arr, owners, way_geom = load_arrondissements(elements)
    if sorted(arr) != list(range(1, 10)):
        raise SystemExit(f"expected arrondissements 1-9, found {sorted(arr)}")
    rivers = build_rivers(owners, way_geom)
    streets, outside = build_streets(elements, arr)

    data = {
        "origin": [ORIGIN_LON, ORIGIN_LAT],
        "arr": {str(n): encode_rings(r, RING_SIMPLIFY_M) for n, r in sorted(arr.items())},
        "rivers": {k: encode_rings(v, RING_SIMPLIFY_M) for k, v in rivers.items()},
        "streets": streets,
        "osm": raw["osm3s"]["timestamp_osm_base"],
    }
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")

    ranks = collections.Counter(s[1] for s in streets)
    print(f"{len(streets)} streets ({outside} outside Lyon dropped), by rank {dict(sorted(ranks.items()))}")
    print("rivers:", {k: f"{len(v)} piece(s)" for k, v in rivers.items()})
    print(f"wrote {args.out} ({len(text.encode()) // 1024} KB)")


if __name__ == "__main__":
    main()
