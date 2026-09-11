#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用高德批量补景点，填上还没有 POI 数据的目的地。

用法:
  python scripts/amap_fetch_pois.py --gaps --dry      看哪些目的地是空的
  python scripts/amap_fetch_pois.py --gaps            全部补上
  python scripts/amap_fetch_pois.py --dest 黄山

质量边界（必须说清）：
  高德能给     名称、坐标、评分、地址、营业时间
  高德给不了   网红/小众的判断、出片指数、最佳光线、机位、避坑提示、
               建议停留时长、门票价

所以这批数据 src_confidence 一律 low，note 里标「高德批量拉取」，
停留时长是按 POI 类型套的经验值。人工整理的那 135 条不受影响。
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amap                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POI_CSV = ROOT / "data" / "pois.csv"
DEST_CSV = ROOT / "data" / "destinations.csv"

# 搜索用的类型：风景名胜 + 科教文化（博物馆等）
TYPES = "110000|140000"

# POI 细分类型 -> (建议停留分钟, 归到哪一类)
# 停留时长是经验值，不是高德给的 —— 高德没有这个字段。
STAY_RULES = [
    # 停留时长能按类型套经验值，但**网红/小众/经典的判断高德给不了** ——
    # 那是人工整理的价值。全部标「未分类」，不混进人工的三分类里。
    (("世界遗产", "国家级风景名胜"), 180, "未分类"),
    (("博物馆", "纪念馆", "展览馆", "美术馆", "科技馆"), 120, "未分类"),
    (("动物园", "植物园", "水族馆"), 130, "未分类"),
    (("寺庙", "教堂", "道观", "清真寺"), 50, "未分类"),
    (("公园", "广场"), 70, "未分类"),
    (("风景名胜", "旅游景点", "景区"), 150, "未分类"),
    (("文物古迹", "古迹", "遗址"), 90, "未分类"),
    (("步行街", "商业街"), 60, "未分类"),
]
DEFAULT_STAY, DEFAULT_HOT = 90, "未分类"

BAD_NAME = ("售票", "检票", "停车", "厕所", "出入口", "服务中心", "管理处",
            "派出所", "警务", "医务", "工作站", "打卡点", "导览", "指示牌",
            "充电", "加油", "酒店", "宾馆", "民宿", "客栈", "商店", "超市",
            "办事处", "办公室", "施工", "工程", "项目部")
OPEN_RE = re.compile(r"(\d{1,2}:\d{2})\s*[-–~至]\s*(\d{1,2}:\d{2})")


def classify(poi_type: str):
    t = poi_type or ""
    for keys, stay, hot in STAY_RULES:
        if any(k in t for k in keys):
            return stay, hot
    return DEFAULT_STAY, DEFAULT_HOT


def parse_open(s: str):
    """"周一至周日 08:30-17:30" -> ("08:30","17:30")。解析不了就留空。"""
    m = OPEN_RE.search(s or "")
    if not m:
        return "", ""
    return m.group(1), m.group(2)


def read(p):
    rows = list(csv.reader(io.StringIO(io.open(p, encoding="utf-8-sig").read())))
    return rows[0], rows[1:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gaps", action="store_true", help="补所有没有景点的目的地")
    ap.add_argument("--dest", help="只补这一个目的地（按 destinations.name）")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--min-rating", type=float, default=4.0)
    ap.add_argument("--per-dest", type=int, default=10, help="每个目的地最多收几条")
    a = ap.parse_args()
    if not a.gaps and not a.dest:
        ap.error("要 --gaps 或 --dest 某地")

    phdr, pdata = read(POI_CSV)
    dhdr, ddata = read(DEST_CSV)
    PI = {c: i for i, c in enumerate(phdr)}
    DI = {c: i for i, c in enumerate(dhdr)}

    have_city = {r[PI["city"]] for r in pdata}
    have_name = {(r[PI["city"]], r[PI["name"]]) for r in pdata}
    next_id = max(int(r[0][1:]) for r in pdata) + 1

    if a.dest:
        targets = [r for r in ddata if r[DI["name"]] == a.dest]
        if not targets:
            print("目的地库里没有：", a.dest)
            return 1
    else:
        targets = [r for r in ddata if r[DI["city"]] not in have_city]

    print("要补 %d 个目的地\n" % len(targets))
    if a.dry and a.gaps:
        for r in targets:
            print("  %-16s %s" % (r[DI["name"]], r[DI["city"]]))
        print("\n加 --gaps 不带 --dry 就开始拉。")
        return 0

    added, skipped = [], 0
    for n, dr in enumerate(targets, 1):
        did, dname, city = dr[DI["dest_id"]], dr[DI["name"]], dr[DI["city"]]
        # 用目的地名和城市名各搜一次，取并集 —— 有些目的地名比城市名更准
        pool, seen = [], set()
        for kw in dict.fromkeys([dname, city]):
            for p in amap.poi_search(kw, city, types=TYPES, page_size=20):
                if not p["lng"] or p["name"] in seen:
                    continue
                seen.add(p["name"])
                pool.append(p)

        ok = []
        for p in pool:
            nm = p["name"] or ""
            if any(w in nm for w in BAD_NAME):
                continue
            if p["rating"] is not None and p["rating"] < a.min_rating:
                skipped += 1
                continue
            if (city, nm) in have_name:
                skipped += 1
                continue
            ok.append(p)
        # 有评分的优先，其次评分高的
        ok.sort(key=lambda p: (0 if p["rating"] else 1, -(p["rating"] or 0)))
        ok = ok[:a.per_dest]

        print("  %2d/%d %-16s %s  收 %d 条"
              % (n, len(targets), dname, city, len(ok)))
        for p in ok:
            stay, hot = classify(p["type"])
            op, cl = parse_open(p["opentime"])
            row = [""] * len(phdr)
            def st(c, v): row[PI[c]] = v
            st("poi_id", "P%03d" % next_id); next_id += 1
            st("dest_id", did); st("name", p["name"]); st("city", city)
            st("poi_type", (p["type"] or "").split(";")[-1] or "景点")
            st("lat", "%.6f" % p["lat"]); st("lng", "%.6f" % p["lng"])
            st("official_level", "5A" if "5A" in (p["name"] or "") else "")
            st("hot_type", hot)
            st("hot_note", "高德自动拉取，还没人工判断是网红还是小众")
            st("stay_minutes", str(stay))
            st("open_time", op); st("close_time", cl)
            st("closed_day", ""); st("last_entry", "")
            st("ticket_price", "-1")
            st("booking_rule_id", "")
            st("photo_score", "")
            st("best_light", ""); st("shoot_tip", ""); st("crowd_peak", "")
            st("suit_elderly", "1"); st("suit_kids", "1")
            st("walk_km", ""); st("climb_m", "")
            st("why_worth", ("高德评分 %.1f" % p["rating"]) if p["rating"]
               else "高德收录")
            st("avoid_tip", "")
            st("src_confidence", "low")
            st("verified", "0")
            st("source_url", "高德POI:" + (p["id"] or ""))
            st("note", "高德批量拉取；停留时长按类型套的经验值，"
                       "无出片指数/机位/避坑，需人工补")
            assert len(row) == len(phdr)
            added.append(row)
            have_name.add((city, p["name"]))

    print("\n" + "=" * 62)
    print("新增 %d 条景点，跳过 %d 条（评分不够或已存在）" % (len(added), skipped))
    if added:
        wr = sum(1 for r in added if r[PI["open_time"]])
        print("解析出营业时间的 %d 条" % wr)
        from collections import Counter
        print("分类:", dict(Counter(r[PI["hot_type"]] for r in added)))
        print("覆盖目的地:", len({r[PI["dest_id"]] for r in added}), "个")
    if a.dry:
        print("\n--dry 模式，文件没动。")
        return 0
    if not added:
        return 0
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([phdr] + pdata + added)
    io.open(POI_CSV, "w", encoding="utf-8-sig", newline="").write(buf.getvalue())
    print("\n已写入 pois.csv（%d -> %d 条）" % (len(pdata), len(pdata) + len(added)))
    print("人工整理的那批一条没动。")
    print("别忘了：python scripts/build_web.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
