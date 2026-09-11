#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""为还没有实录路线的城市对生成**估算**路线。

为什么是估算：高德没有城际班次接口（12306 也没有公开 API），
高铁车次、票价、班次密度拿不到。这里只能按两地坐标距离推：

    实际里程 ≈ 直线距离 × 1.3
    1200 公里以内走高铁：等效时速 200km/h（含停站），二等座约 0.45 元/公里
    超过 1200 公里走飞机：700km/h + 2 小时地面时间，票价约 0.75 元/公里

误差不小，**只用来判断远近**，所以：
  mode 后面带「(估)」、src_confidence=low、note 写明非实录。
前端据此显示「估」角标，和实录的 125 条区分开。

用法:
  python scripts/gen_routes.py --dry
  python scripts/gen_routes.py --from 南京 北京 邯郸 上海
"""
from __future__ import annotations

import argparse
import csv
import io
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"

# 默认为这些城市生成 —— 用户常用的出发地 + 主要枢纽
DEFAULT_FROM = ["南京", "北京", "邯郸", "上海", "杭州", "广州", "成都",
                "西安", "深圳", "武汉", "重庆", "长沙", "厦门", "郑州"]


def km(a_lng, a_lat, b_lng, b_lat) -> float:
    R = 6371.0
    dlat = math.radians(b_lat - a_lat)
    dlng = math.radians(b_lng - a_lng)
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) *
         math.sin(dlng / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def read(p):
    rows = list(csv.reader(io.StringIO(io.open(p, encoding="utf-8-sig").read())))
    return rows[0], rows[1:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="froms", nargs="*", default=DEFAULT_FROM)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    rhdr, rdata = read(D / "routes.csv")
    RI = {c: i for i, c in enumerate(rhdr)}
    dests = list(csv.DictReader(open(D / "destinations.csv", encoding="utf-8-sig")))

    # 已有的城市对不重复生成
    have = {(r[RI["from_city"]], r[RI["to_city"]]) for r in rdata}
    next_id = max(int(r[0][1:]) for r in rdata) + 1

    # 出发地坐标：优先用 destinations 里的
    coord = {}
    for d in dests:
        try:
            coord.setdefault(d["name"], (float(d["center_lng"]), float(d["center_lat"])))
            coord.setdefault(d["city"], (float(d["center_lng"]), float(d["center_lat"])))
        except (ValueError, TypeError):
            pass

    added, skipped_have, skipped_nocoord = [], 0, 0
    for f in a.froms:
        if f not in coord:
            print("  出发地 %s 没有坐标，跳过" % f)
            continue
        fl, fa = coord[f]
        n_f = 0
        for d in dests:
            to = d["name"]
            if to == f or d["city"] == f:
                continue
            if (f, to) in have:
                skipped_have += 1
                continue
            try:
                tl, ta = float(d["center_lng"]), float(d["center_lat"])
            except (ValueError, TypeError):
                skipped_nocoord += 1
                continue
            straight = km(fl, fa, tl, ta)
            if straight < 30:          # 太近，算同城
                continue
            real = straight * 1.3
            if real >= 1200:
                mode, dur = "飞机(估)", round(real / 700 * 60 + 120)
                pmin, pmax = round(real * 0.6), round(real * 1.1)
                acc, egr, buf = 80, 70, 110
            else:
                mode, dur = "高铁(估)", round(real / 200 * 60)
                pmin, pmax = round(real * 0.40), round(real * 0.70)
                acc, egr, buf = 40, 35, 30
            row = [""] * len(rhdr)
            def st(c, v): row[RI[c]] = v
            st("route_id", "R%03d" % next_id); next_id += 1
            st("from_city", f); st("to_city", to)
            st("mode", mode); st("train_type", "—")
            st("station_from", ""); st("station_to", "")
            st("duration_min", str(dur))
            st("price_min", str(pmin)); st("price_max", str(pmax))
            st("frequency", "未核实")
            st("access_min", str(acc)); st("egress_min", str(egr))
            st("buffer_min", str(buf))
            st("total_min", str(dur + acc + egr + buf))
            st("transfer_note", "")
            st("book_channel", "航司官网" if "飞机" in mode else "12306")
            st("book_tip", "—")
            st("src_confidence", "low")
            st("verified", "0")
            st("source_url", "")
            st("last_check_date", "")
            st("note", "按直线距离 %d 公里估算，非实录班次；"
                       "具体车次与票价请查 12306 或航司" % round(real))
            assert len(row) == len(rhdr)
            added.append(row); n_f += 1
        print("  %-5s 生成 %d 条" % (f, n_f))

    print("\n" + "=" * 62)
    print("生成 %d 条估算路线（已有的 %d 对没动，%d 个目的地缺坐标）"
          % (len(added), skipped_have, skipped_nocoord))
    if added:
        air = sum(1 for r in added if "飞机" in r[RI["mode"]])
        print("  高铁估算 %d 条，飞机估算 %d 条" % (len(added) - air, air))
        durs = [int(r[RI["duration_min"]]) for r in added]
        print("  车上时间 %d - %d 分钟" % (min(durs), max(durs)))
    if a.dry:
        print("\n--dry 模式，文件没动。")
        return 0
    if not added:
        return 0
    buf2 = io.StringIO()
    csv.writer(buf2, lineterminator="\n").writerows([rhdr] + rdata + added)
    io.open(D / "routes.csv", "w", encoding="utf-8-sig",
            newline="").write(buf2.getvalue())
    print("\n已写入 routes.csv（%d -> %d）" % (len(rdata), len(rdata) + len(added)))
    print("实录的 %d 条一条没动。" % len(rdata))
    return 0


if __name__ == "__main__":
    sys.exit(main())
