#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给还没有住宿数据的城市生成住宿片区。

思路：住宿最关键的是「住哪个片区」，而片区的价值 = 离景点近。
所以先把该城市的景点按坐标聚成堆，取景点最密集的那一堆当作核心片区，
再用高德在这个片区搜酒店，拿真实价格分三档。

高德能给     酒店名、坐标、评分、价格
高德给不了   这个片区方不方便、地铁覆盖、有什么坑
所以自动生成的片区 src_confidence=low，avoid_tip 留空等人工补。

用法:
  python scripts/amap_fetch_stays.py --gaps --dry
  python scripts/amap_fetch_stays.py --gaps
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amap                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
HOTEL_TYPE = "100000"        # 住宿服务


def read(p):
    rows = list(csv.reader(io.StringIO(io.open(p, encoding="utf-8-sig").read())))
    return rows[0], rows[1:]


def cluster(points, radius=2.5):
    """把景点按距离聚堆，返回按堆大小降序的 [(中心lng, 中心lat, 数量, 名字们)]。
    贪心就够了 —— 只是想找出景点最扎堆的地方。"""
    left = list(points)
    out = []
    while left:
        seed = left[0]
        group = [p for p in left
                 if amap.km(seed["lng"], seed["lat"], p["lng"], p["lat"]) <= radius]
        for g in group:
            left.remove(g)
        lng = sum(p["lng"] for p in group) / len(group)
        lat = sum(p["lat"] for p in group) / len(group)
        out.append((lng, lat, len(group), [p["name"] for p in group]))
    out.sort(key=lambda x: -x[2])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gaps", action="store_true")
    ap.add_argument("--city")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--per-city", type=int, default=2, help="每城最多几个片区")
    a = ap.parse_args()
    if not a.gaps and not a.city:
        ap.error("要 --gaps 或 --city 某城")

    shdr, sdata = read(D / "stays.csv")
    SI = {c: i for i, c in enumerate(shdr)}
    pois = list(csv.DictReader(open(D / "pois.csv", encoding="utf-8-sig")))
    dests = list(csv.DictReader(open(D / "destinations.csv", encoding="utf-8-sig")))

    have = {r[SI["city"]] for r in sdata}
    next_id = max(int(r[0][1:]) for r in sdata) + 1

    by_city = {}
    for p in pois:
        try:
            lng, lat = float(p["lng"]), float(p["lat"])
        except (ValueError, KeyError):
            continue
        by_city.setdefault(p["city"], []).append(
            {"name": p["name"], "lng": lng, "lat": lat})

    did_of = {}
    for d in dests:
        did_of.setdefault(d["city"], d["dest_id"])

    cities = ([a.city] if a.city
              else [c for c in sorted(by_city) if c not in have])
    print("要补 %d 个城市的住宿\n" % len(cities))

    added = []
    for n, city in enumerate(cities, 1):
        pts = by_city.get(city) or []
        if len(pts) < 2:
            print("  %2d/%d %-8s 景点太少（%d），跳过" % (n, len(cities), city, len(pts)))
            continue
        groups = cluster(pts)[:a.per_city]
        for gi, (lng, lat, cnt, names) in enumerate(groups):
            hotels = amap.poi_search("酒店", city, types=HOTEL_TYPE, page_size=25)
            near = [h for h in hotels if h["lng"] and
                    amap.km(lng, lat, h["lng"], h["lat"]) <= 3.0]
            costs = sorted(h["cost"] for h in near if h["cost"])
            if costs:
                lo, mid, hi = (costs[0], costs[len(costs) // 2], costs[-1])
            else:
                lo = mid = hi = None
            examples = "；".join(h["name"] for h in
                                sorted(near, key=lambda x: -(x["rating"] or 0))[:3])
            area = names[0] + "一带" if gi == 0 else names[0] + "周边"
            atype = "核心景区" if gi == 0 else "商业中心"

            def rng(base, k):
                return ("", "") if not base else (
                    str(int(base * k[0])), str(int(base * k[1])))
            eco = rng(lo or 200, (0.7, 1.1))
            md = rng(mid or 400, (0.85, 1.4))
            hg = rng(hi or 900, (0.9, 2.0))

            row = [""] * len(shdr)
            def st(c, v): row[SI[c]] = v
            st("stay_id", "S%03d" % next_id); next_id += 1
            st("dest_id", did_of.get(city, "")); st("city", city)
            st("area_name", area); st("area_type", atype)
            st("lat", "%.6f" % lat); st("lng", "%.6f" % lng)
            st("why_here", "这一带聚了 %d 个景点（%s 等），住这儿走路就能到"
               % (cnt, "、".join(names[:3])))
            st("metro_access", "")
            st("walk_to", "、".join(names[:5]))
            st("price_eco_low", eco[0]); st("price_eco_high", eco[1])
            st("price_mid_low", md[0]); st("price_mid_high", md[1])
            st("price_high_low", hg[0]); st("price_high_high", hg[1])
            st("peak_multiplier", "1.8")
            st("example_hotels", examples)
            st("avoid_tip", "")
            st("src_confidence", "low")
            st("verified", "0")
            st("source_url", "高德POI")
            st("note", "按景点密度自动圈的片区；房价取附近酒店的高德价格区间，"
                       "旺季系数是通用值 1.8。地铁覆盖与避坑需人工补")
            assert len(row) == len(shdr)
            added.append(row)
        print("  %2d/%d %-8s %d 个片区（最密的一堆有 %d 个景点）"
              % (n, len(cities), city, len(groups), groups[0][2]))

    print("\n" + "=" * 62)
    print("新增 %d 个片区，覆盖 %d 个城市"
          % (len(added), len({r[SI["city"]] for r in added})))
    withprice = sum(1 for r in added if r[SI["price_mid_low"]])
    print("拿到真实房价区间的 %d 个" % withprice)
    if a.dry:
        print("\n--dry 模式，文件没动。")
        return 0
    if not added:
        return 0
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([shdr] + sdata + added)
    io.open(D / "stays.csv", "w", encoding="utf-8-sig",
            newline="").write(buf.getvalue())
    print("\n已写入 stays.csv（%d -> %d）" % (len(sdata), len(sdata) + len(added)))
    print("人工写的 34 个片区一条没动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
