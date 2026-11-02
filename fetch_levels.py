#!/usr/bin/env python3
"""
Pulls river level readings for the River Ure gauges from the Environment Agency
open flood-monitoring API and appends them to CSV files in ./data.

- Finds the gauges itself (see config.json), so new gauges appear automatically.
- First run backfills from BACKFILL_FROM (as far as the API holds data).
- Later runs only fetch what's new, and fill any gap if a run was missed.
- Standard library only, no installs needed.

Data: Environment Agency real-time flood-monitoring API, Open Government Licence v3.
"""
import bisect
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
API = "https://environment.data.gov.uk/flood-monitoring"
CHUNK_DAYS = 14          # 14 days of 15-minute readings = ~1,350 rows, well under the 10,000 cap
UA = "ure-levels-logger/1.0 (personal angling project)"


def get_json(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # network blip, 5xx, etc.
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500:
                print(f"  ! {e.code} for {url}", file=sys.stderr)
                return None
            if attempt == tries - 1:
                print(f"  ! giving up on {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))


def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def load_config():
    with open(os.path.join(ROOT, "config.json")) as f:
        return json.load(f)


def norm_river(name):
    if not name:
        return "Other"
    return name if name.startswith("River ") else "River " + name


def discover_stations(cfg):
    """Find every level gauge on the configured rivers, plus any explicitly listed."""
    found = {}
    queries = [{"riverName": r} for r in cfg.get("river_names", [])]
    queries += [{"RLOIid": str(i)} for i in cfg.get("extra_rloi_ids", [])]
    queries += [{"search": g["match"]} for g in cfg.get("gauges", [])]   # catches gauges filed under an unexpected river name
    for q in queries:
        q = dict(q, parameter="level", _limit=200)
        url = f"{API}/id/stations?" + urllib.parse.urlencode(q)
        res = get_json(url)
        for s in (res or {}).get("items", []):
            found[s["stationReference"]] = s
    exclude = set(str(x) for x in cfg.get("exclude_station_references", []))
    bb = cfg.get("bounding_box")   # keeps out other rivers that share a name (e.g. the Sussex Ouse)
    order = [norm_river(r) for r in cfg.get("river_names", [])]
    stations = []
    for ref, s in found.items():
        if ref in exclude:
            continue
        if bb and s.get("lat") is not None and not (
                bb["min_lat"] <= s["lat"] <= bb["max_lat"] and bb["min_lon"] <= s["long"] <= bb["max_lon"]):
            continue
        measures = [m for m in as_list(s.get("measures")) if m.get("parameter") == "level"]
        if not measures:
            continue
        # Prefer the normal "stage" level measure (water height above gauge datum)
        measures.sort(key=lambda m: (m.get("qualifier") != "Stage", m.get("@id", "")))
        m = measures[0]
        lat, lon = s.get("lat"), s.get("long")
        stations.append({
            "ref": ref,
            "rloi": s.get("RLOIid"),
            "label": s.get("label"),
            "river": norm_river(s.get("riverName")),
            "tidal": m.get("qualifier") == "Tidal Level",
            "town": s.get("town"),
            "lat": lat,
            "lon": lon,
            "measure": m["@id"].replace("http://", "https://"),
            "unit": m.get("unitName", "m"),
            "typical_low": (s.get("stageScale") or {}).get("typicalRangeLow") if isinstance(s.get("stageScale"), dict) else None,
            "typical_high": (s.get("stageScale") or {}).get("typicalRangeHigh") if isinstance(s.get("stageScale"), dict) else None,
            "url": f"https://check-for-flooding.service.gov.uk/station/{s.get('RLOIid')}" if s.get("RLOIid") else None,
        })
    wanted = cfg.get("gauges")
    if wanted:
        kept, unmatched = [], []
        for i, g in enumerate(wanted):
            hits = [st for st in stations
                    if g["match"].lower() in (st["label"] or "").lower()
                    and (not g.get("river") or st["river"] == norm_river(g["river"]))]
            if not hits:
                unmatched.append(g["match"])
            for st in hits:
                st["order"] = i
                if g.get("group"):
                    st["river"] = norm_river(g["group"])   # heading it appears under on the page
                if g.get("tidal"):
                    st["tidal"] = True
                if g.get("tide_link"):
                    st["tide_link"] = g["tide_link"]
                if st not in kept:
                    kept.append(st)
            print(f"  '{g['match']}' -> {[h['label'] + ' (' + str(h['river']) + ')' for h in hits] or 'NO MATCH'}")
        if unmatched:
            print("  ! No gauge matched: " + ", ".join(unmatched) + " (see the list below for names the API does have)", file=sys.stderr)
            print("  Gauges the API listed: " + "; ".join(sorted(f"{s['label']} ({s['river']})" for s in stations)), file=sys.stderr)
        stations = sorted(kept, key=lambda s: s["order"])
    else:
        # group by river in the order given in config.json; within a river, north (upstream) first
        stations.sort(key=lambda s: (order.index(s["river"]) if s["river"] in order else 99, -(s["lat"] or 0)))
    return stations


def read_csv(path):
    rows = {}
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.reader(f):
                if r and r[0] != "dateTime":
                    rows[r[0]] = r[1]
    return rows


def write_csv(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["dateTime", "value"])
        for k in sorted(rows):
            w.writerow([k, rows[k]])
    os.replace(tmp, path)


def fetch_range(measure, start, end):
    q = f"startdate={start.isoformat()}&enddate={end.isoformat()}&_sorted&_limit=10000"
    res = get_json(f"{measure}/readings?{q}")
    out = {}
    for it in (res or {}).get("items", []):
        v = it.get("value")
        if isinstance(v, list):  # occasionally a list when a reading has 2 values
            v = v[0] if v else None
        if v is None or not it.get("dateTime"):
            continue
        out[it["dateTime"]] = f"{float(v):.3f}"
    return out


def main():
    cfg = load_config()
    os.makedirs(DATA, exist_ok=True)
    backfill_from = date.fromisoformat(os.environ.get("BACKFILL_FROM", cfg.get("backfill_from", "2025-01-01")))
    today = datetime.now(timezone.utc).date()

    stations = discover_stations(cfg)
    if not stations:
        print("No stations found - API unreachable or river names wrong. Leaving data untouched.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(stations)} gauges")

    for st in stations:
        path = os.path.join(DATA, f"{st['ref']}.csv")
        rows = read_csv(path)
        if rows:
            last = max(rows)[:10]
            start = date.fromisoformat(last) - timedelta(days=1)   # small overlap, dedupe handles it
        else:
            start = backfill_from
        added = 0
        d = start
        while d <= today:
            e = min(d + timedelta(days=CHUNK_DAYS - 1), today)
            new = fetch_range(st["measure"], d, e)
            added += sum(1 for k in new if k not in rows)
            rows.update(new)
            d = e + timedelta(days=1)
            time.sleep(0.3)  # be polite to the API
        if rows:
            write_csv(path, rows)
            st["first"], st["last"] = min(rows), max(rows)
            st["latest_value"] = rows[st["last"]]
            keys = sorted(rows)
            lt = datetime.fromisoformat(st["last"].replace("Z", "+00:00"))
            for hrs in (1, 6):
                target = (lt - timedelta(hours=hrs)).strftime("%Y-%m-%dT%H:%M:%SZ")
                i = bisect.bisect_left(keys, target)
                if i < len(keys) and keys[i] < st["last"]:
                    st[f"change_{hrs}h"] = round(float(rows[st["last"]]) - float(rows[keys[i]]), 3)
            st["count"] = len(rows)
        print(f"  {st['label']}: +{added} readings, {len(rows)} total")

    stations = [s for s in stations if s.get("count")]
    meta = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stations": stations}
    with open(os.path.join(DATA, "stations.json"), "w") as f:
        json.dump(meta, f, indent=1)


if __name__ == "__main__":
    main()
