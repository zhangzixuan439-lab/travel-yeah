#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 data/*.csv 编译成前端用的 data.js（改完任何 CSV 跑一次）。

用法: python scripts/build_web.py [--minify]
产物: data.js —— 供 index.html 直接 <script src> 引用，离线可用
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "data.js"

# CSV 文件 -> 前端 key
TABLES = {
    "booking_rules": "rules",
    "destinations":  "dests",
    "pois":          "pois",
    "foods":         "foods",
    "routes":        "routes",
    "transits":      "transits",
    "arrivals":      "arrivals",
    "stays":         "stays",
}

# 需要转成数字的列（跨表统一处理，缺失/空 -> None）
INT_COLS = {
    "need_booking", "advance_days", "time_slot", "daily_quota", "difficulty",
    "need_id_card", "need_companion_id", "verified",
    "suggest_days_min", "suggest_days_max", "tag_photo", "tag_food",
    "tag_nature", "tag_culture", "tag_kids", "tag_chill", "tag_niche",
    "consume_level", "crowd_holiday", "crowd_weekday", "altitude_m",
    "stay_minutes", "photo_score", "suit_elderly", "suit_kids", "climb_m",
    "price_confidence_n", "list_year", "queue_level", "is_local_only",
    "duration_min", "access_min", "egress_min", "buffer_min", "total_min",
    "walk_min", "taxi_min", "price",
    "price_eco_low", "price_eco_high", "price_mid_low", "price_mid_high",
    "price_high_low", "price_high_high",
}
FLOAT_COLS = {"lat", "lng", "center_lat", "center_lng", "ticket_price",
              "walk_km", "price_per_person", "price_min", "price_max",
              "taxi_price", "peak_multiplier", "rating"}


def cast(col: str, val: str):
    val = (val or "").strip()
    if val == "":
        return None
    if col in INT_COLS:
        return int(val) if val.lstrip("-").isdigit() else None
    if col in FLOAT_COLS:
        try:
            return float(val)
        except ValueError:
            return None
    return val


def load(name: str) -> list[dict]:
    path = DATA / (name + ".csv")
    if not path.exists():
        print("  跳过 %s（文件不存在）" % path.name)
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [{k: cast(k, v) for k, v in r.items()} for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minify", action="store_true",
                    help="去掉 note/source_url 等前端不用的字段，减小体积")
    a = ap.parse_args()

    payload = {"built_at": date.today().isoformat()}
    stats = []
    for fname, key in TABLES.items():
        rows = load(fname)
        if a.minify:
            drop = {"note", "source_url", "hot_note"}
            rows = [{k: v for k, v in r.items() if k not in drop} for r in rows]
        payload[key] = rows
        stats.append((fname, len(rows)))

    # 派生：城市列表按条数降序，前端 chips 直接用
    rules = payload.get("rules", [])
    cities = sorted({r["city"] for r in rules if r.get("city")})
    cities.sort(key=lambda c: (-sum(1 for r in rules if r["city"] == c), c))
    payload["cities"] = cities
    payload["count"] = len(rules)

    # 派生：知识库覆盖的城市（景点/美食页签用）
    kb_cities = sorted({r["city"] for r in payload.get("pois", []) if r.get("city")}
                       | {r["city"] for r in payload.get("foods", []) if r.get("city")})
    payload["kb_cities"] = kb_cities

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(
        "/* 由 scripts/build_web.py 生成，不要手改 —— 改 data/*.csv 后重跑 */\n"
        "window.BOOKING_DATA = " + body + ";\n",
        encoding="utf-8")

    print("data.js 已生成：%.1f KB" % (OUT.stat().st_size / 1024))
    for fname, n in stats:
        print("  %-16s %3d 条" % (fname, n))
    print("  预约规则覆盖城市 %d 个 / 知识库覆盖城市 %d 个"
          % (len(cities), len(kb_cities)))

    # 数据质量提示
    pois = payload.get("pois", [])
    foods = payload.get("foods", [])
    if pois:
        hot = {}
        for r in pois:
            hot[r.get("hot_type")] = hot.get(r.get("hot_type"), 0) + 1
        print("  景点分类:", "  ".join("%s %d" % kv for kv in sorted(hot.items())))
    if foods:
        named = sum(1 for r in foods if r.get("store_name") not in (None, "—"))
        print("  美食有店名 %d / %d 条" % (named, len(foods)))
    unver = sum(1 for key in ("rules", "dests", "pois", "foods", "routes", "transits")
                for r in payload.get(key, []) if r.get("verified") != 1)
    print("  待核实 %d 条（全库）" % unver)
    return 0


if __name__ == "__main__":
    sys.exit(main())
