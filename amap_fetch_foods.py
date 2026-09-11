#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用高德 POI 搜索批量补餐厅（带真实评分、人均、营业时间）。

用法:
  python scripts/amap_fetch_foods.py --city 厦门 --dry
  python scripts/amap_fetch_foods.py --city 厦门 --min-rating 4.3
  python scripts/amap_fetch_foods.py --all --min-rating 4.3 --per-dish 3

设计取向：
  1. 不是无脑拉一堆店。按**该城市的本地菜品**去搜（沙茶面、臭豆腐、
     羊肉泡馍…），这样拉到的是"当地该吃什么"，而不是随便一堆餐厅。
  2. 只收评分达标的。高德评分是它自己的数据，不是点评的，但至少是
     真实来源 —— 填进 rating_source='高德'，跟我手填的估值区分开。
  3. 手工录入的老字号**不覆盖**，只补充。人工写的避坑信息比评分值钱。
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
CSV = ROOT / "data" / "foods.csv"
REST = "050000"          # 高德餐饮服务大类

# 每个城市按本地菜去搜，而不是搜"餐厅"。
# 键是 dest_id，值是 (城市, [菜品...])
CITY_DISHES = {
    "D001": ("成都", ["火锅", "串串香", "麻婆豆腐", "钟水饺", "肥肠粉",
                      "甜水面", "冒菜", "兔头"]),
    "D002": ("西安", ["羊肉泡馍", "肉夹馍", "凉皮", "葫芦头", "水盆羊肉",
                      "biangbiang面", "甑糕"]),
    "D003": ("杭州", ["杭帮菜", "片儿川", "西湖醋鱼", "虾爆鳝面", "葱包烩",
                      "定胜糕"]),
    "D004": ("重庆", ["火锅", "小面", "毛血旺", "酸辣粉", "烤鱼", "江湖菜"]),
    "D013": ("上海", ["本帮菜", "生煎", "小笼", "葱油饼", "排骨年糕",
                      "蟹壳黄", "腌笃鲜"]),
    "D014": ("苏州", ["苏帮菜", "苏式汤面", "松鼠鳜鱼", "生煎", "糕团",
                      "奥灶面"]),
    "D015": ("南京", ["盐水鸭", "皮肚面", "汤包", "鸭血粉丝汤", "锅贴",
                      "牛肉锅贴", "糖粥藕"]),
    "D023": ("长沙", ["湘菜", "臭豆腐", "口味虾", "糖油粑粑", "米粉",
                      "剁椒鱼头", "钵子菜"]),
    "D024": ("张家界", ["土家菜", "三下锅", "腊肉"]),
    "D025": ("湘西", ["湘西菜", "血粑鸭", "米豆腐"]),
    "D043": ("北京", ["烤鸭", "涮羊肉", "炸酱面", "卤煮", "爆肚", "豆汁",
                      "烧麦", "京菜"]),
    "D047": ("邯郸", ["烧鸡", "拽面", "骨酥鱼", "驴肉火烧", "河北菜"]),
    "D057": ("厦门", ["沙茶面", "海蛎煎", "土笋冻", "姜母鸭", "花生汤",
                      "闽南菜", "烧肉粽", "面线糊"]),
    "D058": ("泉州", ["面线糊", "闽南菜", "牛肉羹", "润饼菜", "姜母鸭"]),
}

# 没在 CITY_DISHES 里配菜单的城市用这组通用词。
# 拿到的不如按本地菜搜精准，但总比这个城市一条美食都没有强。
GENERIC = ["本地特色菜", "老字号", "特色小吃", "农家菜", "私房菜"]

BAD_NAME = ("旗舰店", "加盟", "招商", "总部", "培训", "配送", "外卖",
            "预制", "食品厂", "批发")

import re as _re
_PAREN = _re.compile(r"[（(][^）)]*[）)]")


def brand(name: str) -> str:
    """取品牌名（去掉分店后缀）。"临家闽南菜(环岛路店)" -> "临家闽南菜"。
    同品牌只收一家，否则一条街的连锁分店会把列表刷满。"""
    return _PAREN.sub("", name or "").strip()


def dish_of(query: str, p) -> tuple:
    """高德是模糊搜索 —— 搜"土笋冻"会返回"柳河沙茶面"。
    店名里真含搜索词才敢标成那道菜，否则退回用高德的细分类型。"""
    nm = p.get("name") or ""
    if query in nm:
        return query, True
    t = (p.get("type") or "").split(";")
    fine = (t[-1] or t[0] or "餐厅").strip() if t else "餐厅"
    return fine, False


def data_cities(data, I):
    """已经有美食的城市。"""
    return [{"city": r[I["city"]]} for r in data]


def load_csv():
    rows = list(csv.reader(io.StringIO(
        io.open(CSV, encoding="utf-8-sig").read())))
    return rows[0], rows[1:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", help="只处理这个城市")
    ap.add_argument("--all", action="store_true", help="处理全部配了菜单的城市")
    ap.add_argument("--gaps", action="store_true",
                    help="给所有还没美食的城市补（用通用关键词）")
    ap.add_argument("--dry", action="store_true", help="只看不写")
    ap.add_argument("--min-rating", type=float, default=4.3,
                    help="低于这个评分的不收（默认 4.3）")
    ap.add_argument("--per-dish", type=int, default=3,
                    help="每个菜品最多收几家（默认 3）")
    a = ap.parse_args()
    if not a.city and not a.all and not a.gaps:
        ap.error("要 --city 某城 / --all / --gaps")

    hdr, data = load_csv()
    I = {c: i for i, c in enumerate(hdr)}
    have = {(r[I["city"]], r[I["store_name"]]) for r in data}
    have_brand = {(r[I["city"]], brand(r[I["store_name"]])) for r in data
                  if r[I["store_name"]] and r[I["store_name"]] != "—"}
    have_dish = {(r[I["city"]], r[I["dish_name"]]) for r in data}
    next_id = max(int(r[0][1:]) for r in data) + 1

    if a.gaps:
        # 有景点但还没美食的城市，用通用关键词补
        import csv as _csv
        dd = list(_csv.DictReader(open(ROOT / "data" / "destinations.csv",
                                       encoding="utf-8-sig")))
        pp = list(_csv.DictReader(open(ROOT / "data" / "pois.csv",
                                       encoding="utf-8-sig")))
        has_poi = {r["city"] for r in pp}
        has_food = {r["city"] for r in data_cities(data, I)}
        seen_city = set()
        targets = []
        for r in dd:
            c = r["city"]
            if c in seen_city or c not in has_poi or c in has_food:
                continue
            seen_city.add(c)
            targets.append((r["dest_id"], c, GENERIC))
    else:
        targets = [(d, c, dishes) for d, (c, dishes) in CITY_DISHES.items()
                   if a.all or c == a.city]
    if not targets:
        print("没有匹配的城市。已配置：%s"
              % "、".join(c for c, _ in CITY_DISHES.values()))
        return 1

    added, skipped_low, skipped_dup = [], 0, 0
    for did, city, dishes in targets:
        print("\n=== %s（%d 个菜品）===" % (city, len(dishes)))
        for dish in dishes:
            ps = amap.poi_search(dish, city, types=REST, page_size=20)
            ok = []
            for p in ps:
                nm = p["name"] or ""
                if any(w in nm for w in BAD_NAME):
                    continue
                if p["rating"] is None or p["rating"] < a.min_rating:
                    skipped_low += 1
                    continue
                if (city, nm) in have or (city, brand(nm)) in have_brand:
                    skipped_dup += 1
                    continue
                ok.append(p)
            # 店名真含搜索词的优先，其次按评分
            ok.sort(key=lambda p: (0 if dish in (p["name"] or "") else 1,
                                   -(p["rating"] or 0)))
            picked, seen_brand = [], set()
            for p in ok:
                b = brand(p["name"])
                if b in seen_brand:          # 同品牌只收一家
                    skipped_dup += 1
                    continue
                seen_brand.add(b)
                picked.append(p)
                if len(picked) >= a.per_dish:
                    break
            ok = picked
            if not ok:
                print("  %-12s 无达标结果" % dish)
                continue
            print("  %-12s" % dish, end="")
            for p in ok:
                dn, exact = dish_of(dish, p)
                print(" | %s %.1f分 ¥%s%s"
                      % (p["name"][:13], p["rating"],
                         int(p["cost"]) if p["cost"] else "?",
                         "" if exact else "[%s]" % dn), end="")
                row = [""] * len(hdr)
                def st(c, v): row[I[c]] = v
                st("food_id", "F%03d" % next_id); next_id += 1
                st("dest_id", did); st("city", city)
                st("dish_name", dn); st("store_name", p["name"])
                st("address", p["address"] or "")
                st("lat", "%.6f" % p["lat"] if p["lat"] else "")
                st("lng", "%.6f" % p["lng"] if p["lng"] else "")
                st("price_per_person", "%.0f" % p["cost"] if p["cost"] else "-1")
                st("price_confidence", "mid" if p["cost"] else "low")
                st("rating", "%.1f" % p["rating"])
                st("rating_source", "高德")
                st("list_source", "高德POI")
                st("queue_level", "")
                st("open_time", (p["opentime"] or "")[:40])
                st("is_local_only", "1")
                st("why_worth", ("高德评分 %.1f 的%s店" % (p["rating"], dn))
                   if exact else
                   ("高德评分 %.1f；搜「%s」时命中，实际是%s"
                    % (p["rating"], dish, dn)))
                st("avoid_tip", "")
                st("src_confidence", "mid")
                st("verified", "0")
                st("source_url", "高德POI:" + (p["id"] or ""))
                st("note", "高德批量拉取；评分与人均来自高德，非大众点评")
                added.append(row)
                have.add((city, p["name"]))
                have_brand.add((city, brand(p["name"])))
            print()

    print("\n" + "=" * 62)
    print("新增 %d 条（评分 >= %.1f）" % (len(added), a.min_rating))
    print("跳过：评分不达标或无评分 %d，已存在 %d" % (skipped_low, skipped_dup))
    if added:
        rs = [float(r[I["rating"]]) for r in added]
        cs = [float(r[I["price_per_person"]]) for r in added
              if r[I["price_per_person"]] not in ("", "-1")]
        print("评分 %.1f - %.1f（均值 %.2f）"
              % (min(rs), max(rs), sum(rs) / len(rs)))
        if cs:
            print("人均 ¥%.0f - ¥%.0f（均值 ¥%.0f）"
                  % (min(cs), max(cs), sum(cs) / len(cs)))
        print("带营业时间的 %d 条"
              % sum(1 for r in added if r[I["open_time"]]))

    if a.dry:
        print("\n--dry 模式，文件没动。")
        return 0
    if not added:
        return 0
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([hdr] + data + added)
    io.open(CSV, "w", encoding="utf-8-sig", newline="").write(buf.getvalue())
    print("\n已写入 %s（%d -> %d 条）"
          % (CSV.name, len(data), len(data) + len(added)))
    print("手工录入的老字号一条没动 —— 人工写的避坑信息比评分值钱。")
    print("别忘了：python scripts/build_web.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
