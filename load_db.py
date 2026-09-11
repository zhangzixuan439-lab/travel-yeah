#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 data/*.csv 全部重建进 travel.db（改完 CSV 就跑一次）。

用法: python scripts/load_db.py [--db travel.db]
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# (CSV 文件名, 表名, 建表脚本)
TABLES = [
    ("booking_rules", "booking_rule", "schema.sql"),
    ("destinations",  "destination",  "schema_kb.sql"),
    ("pois",          "poi",          "schema_kb.sql"),
    ("foods",         "food",         "schema_kb.sql"),
    ("routes",        "route",        "schema_kb.sql"),
    ("transits",      "transit",      "schema_kb.sql"),
    ("arrivals",      "arrival",      "schema_kb.sql"),
    ("stays",         "stay",         "schema_kb.sql"),
]

INT_COLS = {
    "need_booking", "advance_days", "time_slot", "daily_quota", "difficulty",
    "need_id_card", "need_companion_id", "verified",
    "suggest_days_min", "suggest_days_max", "tag_photo", "tag_food",
    "tag_nature", "tag_culture", "tag_kids", "tag_chill", "tag_niche",
    "consume_level", "crowd_holiday", "crowd_weekday", "altitude_m",
    "stay_minutes", "photo_score", "suit_elderly", "suit_kids", "climb_m",
    "list_year", "queue_level", "is_local_only",
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "travel.db"))
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    # 建表脚本各自跑一次（schema_kb.sql 含 5 张表，只需执行一遍）
    for script in dict.fromkeys(s for _, _, s in TABLES):
        path = DATA / script
        if not path.exists():
            print("缺少建表脚本:", path)
            return 1
        con.executescript(path.read_text(encoding="utf-8"))

    total = 0
    for fname, table, _ in TABLES:
        csv_path = DATA / (fname + ".csv")
        if not csv_path.exists():
            print("  %-14s 跳过（无 CSV）" % fname)
            continue
        rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
        if not rows:
            continue
        cols = list(rows[0].keys())

        # CSV 列必须和表列完全一致，否则静默错位
        db_cols = [d[1] for d in con.execute("PRAGMA table_info(%s)" % table)]
        if cols != db_cols:
            print("  %-14s 列不匹配！" % fname)
            print("    CSV 有表没有:", [c for c in cols if c not in db_cols])
            print("    表有 CSV 没有:", [c for c in db_cols if c not in cols])
            return 1

        con.executemany(
            "INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(cols))),
            [tuple(cast(c, r[c]) for c in cols) for r in rows])
        print("  %-14s -> %-12s %3d 条" % (fname, table, len(rows)))
        total += len(rows)
    con.commit()

    print("\n%s：共 %d 条" % (a.db, total))
    for view, label in [("v_stale_rule", "预约规则待核实"),
                        ("v_kb_stale", "知识库待核实")]:
        try:
            n = con.execute("SELECT count(*) FROM %s" % view).fetchone()[0]
            print("  %s: %d 条" % (label, n))
        except sqlite3.Error as e:
            print("  %s 查询失败: %s" % (view, e))

    print("\n试试这些查询：")
    print("  SELECT name,hot_type,stay_minutes,photo_score FROM poi"
          " WHERE city='杭州' AND hot_type='小众';")
    print("  SELECT store_name,dish_name,price_per_person,avoid_tip FROM food"
          " WHERE list_source='中华老字号';")
    print("  SELECT to_city,mode,duration_min,total_min,price_min FROM route"
          " WHERE from_city='上海' ORDER BY total_min;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
