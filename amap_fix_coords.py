#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用高德 POI 搜索校正 pois.csv 的坐标（把估值换成真值）。

用法:
  python scripts/amap_fix_coords.py --dry        只看差异，不改文件
  python scripts/amap_fix_coords.py              自动改差异 <= 2km 的
  python scripts/amap_fix_coords.py --city 厦门   只处理一个城市

安全阈值：差异超过 2km 的**不自动改**，列出来人工判断 ——
名称匹配到别的地方（同名店、分馆、另一个城市的同名点）就是这么出错的。
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
CSV = ROOT / "data" / "pois.csv"
# 高德的坐标比我手填的估值可信得多 —— 邯郸那几个郊县景点我原来错了 5-19 公里。
# 搜索已经用 city_limit 限定了城市，所以同城范围内的差异一律采信高德；
# 只有超过这个距离才怀疑是匹配到了别的地方。
AUTO_KM = 30.0
SPLIT = re.compile(r"[与和、（(]")

# 高德 typecode 大类。只认可能是"景点"的类型 ——
# 不过滤的话会匹配到房产中介（倍家房产(铁路文化公园店)）和停车场。
OK_TYPES = {
    "11",   # 风景名胜
    "14",   # 科教文化服务（博物馆、学校、展馆）
    "08",   # 体育休闲服务（公园里的场馆）
    "19",   # 地名地址信息（"曾厝垵"这类片区名）
    "20",   # 公共设施
    "13",   # 政府机构及社会团体（部分纪念馆挂这个）
}
BAD_TYPES = {
    "05",   # 餐饮
    "06",   # 购物
    "07",   # 生活服务
    "09",   # 医疗
    "10",   # 住宿
    "12",   # 商务住宅（房地产中介就在这）
    "15",   # 交通设施（停车场、车站）
    "16",   # 金融
    "17",   # 公司企业
    "18",   # 道路附属
}
# 名字里出现这些词，基本可以断定不是景点本体
BAD_WORDS = ("房产", "中介", "停车场", "售楼", "地产", "物业", "广告",
             "装饰", "建材", "超市", "便利店", "药店", "网吧", "公寓",
             "宾馆", "酒店", "旅馆", "民宿", "客栈")

# 候选名里比查询名多出来的那部分如果含这些词，说明它是"挂在景点名下的
# 另一个东西"而不是景点本体：水陆庵 -> 水陆庵中学、天府熊猫塔 -> 警务工作站、
# 广府古城 -> 广府古城水上乐园、汉阳陵 -> 汉阳陵舞乐俑(打卡点)。
NOT_BODY = ("中学", "小学", "幼儿园", "派出所", "警务", "工作站", "居委会",
            "水上乐园", "游乐园", "工程", "项目", "打卡点", "售票", "检票",
            "管理处", "指挥部", "服务中心", "分店", "旗舰店", "专卖",
            "培训", "医院", "诊所", "银行", "营业厅", "加油站", "充电")
CONFIRM_KM = 10.0        # 移动超过这个距离，即使名字对得上也要人工确认

# 确认过是对的（我原来估错了，高德是准的）。
# 反面教材："回车巷"在邯郸市区串城街，但成安县也有个同名的回车巷，
# 而 city_limit 只限到市级，所以会误配到 17 公里外 —— 这条不能接受。
CONFIRMED = ("龙泉山城市之眼", "邺城遗址与邺城博物馆", "京娘湖")


PAREN = re.compile(r"[（(][^）)]*[）)]")
STATION = ("公交站", "地铁站", "(站)", "车站", "站台")


def norm(x: str) -> str:
    """剥掉括号再比 —— "第八市场(八市)" 要能对上 "八市第八菜市场"。"""
    return PAREN.sub("", x or "").strip()


def is_station(nm: str) -> bool:
    """公交站/地铁站的坐标不是景区本体，能选别的就别选它。"""
    return any(w in (nm or "") for w in STATION)


def overlap(a: str, b: str) -> float:
    """字符重合率。比子串包含宽松，能认出"景山万春亭"和"景山公园-万春亭"，
    也能认出"八市第八菜市场"和"第八市场"，但"沙坡尾"和"地面停车场"是 0。"""
    sa = set(a) - set("（）()-· ")
    sb = set(b) - set("（）()-· ")
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def accept(query: str, p) -> tuple:
    """判断这个候选能不能用。返回 (能不能, 原因)。

    分两级，因为大类拉黑太粗：菜市场和特色商业街在高德归"购物服务"，
    整类拉黑会把"第八市场(八市)"这种正确匹配也挡掉。
      一级：名字完全对上 -> 直接认（只要不含明显无关词）
      二级：名字只部分重合 -> 才查类型白名单
    """
    nm = p.get("name") or ""
    if not nm:
        return False, "无名字"
    if any(w in nm for w in BAD_WORDS):
        return False, "名字含无关词"

    # 这两项必须在"名字包含"判定之前 ——
    # "水陆庵" in "水陆庵中学" 会直接通过，就查不到"中学"了。
    # 而且要用原始名查，剥了括号"(打卡点)"就没了。
    hit_not_body = [w for w in NOT_BODY if w in nm]
    if hit_not_body:
        return False, "挂在景点名下的其它场所(%s)" % hit_not_body[0]

    q, n2 = norm(query), norm(nm)
    if q and n2 and (q in n2 or n2 in q):
        return True, "名字对上"

    tc = (p.get("typecode") or "")[:2]
    sq = set(q) - set("（）()-· ")
    sn = set(n2) - set("（）()-· ")
    ov = overlap(q, n2)

    # 要求查询名的每个字都出现在候选名里。
    # 中文常用字天然重合度高 —— "湖南博物院" 和 "湖南省地质博物馆" 有 80%
    # 字符重合，却是两个完全不同的馆；差的就是那个"院"字。
    if sq and sq <= sn:
        if tc in BAD_TYPES:
            return False, "字全含但类型不符(%s)" % (p.get("type") or "?")
        return True, "查询名的字全部命中"

    missing = "".join(sorted(sq - sn))
    if tc in BAD_TYPES:
        return False, "%s / 缺字'%s'" % (p.get("type") or "类型不符", missing[:6])
    return False, "缺字'%s'(重合%.0f%%)" % (missing[:6], ov * 100)


# 我的命名和高德官方名不一致的，手工给个别名。
# 这是一次性人工活，但比放宽匹配规则安全 —— 放宽会把
# "湖南博物院" 错配到 "湖南省地质博物馆"。
ALIAS = {
    "八市第八菜市场": "第八市场",
    "崇明东滩湿地": "上海东滩湿地公园",
    "五塔寺石刻博物馆": "北京石刻艺术博物馆",
    "山城第三步道": "山城步道",
    "成都远洋太古里与大慈寺": "成都太古里",
    "民生码头八万吨筒仓": "八万吨筒仓",
    "莫干山民宿区": "莫干山风景区",
    "华新路老别墅区": "华新路",
    "汉阳陵博物院": "汉阳陵",
    "龙泉山城市之眼": "丹景台",
    "台城明城墙": "南京城墙台城景区",
    "西湖断桥与白堤": "断桥残雪",
    "武灵丛台": "丛台公园",
}


def search_name(name: str) -> list[str]:
    """我的命名习惯是复合名（"武侯祠与锦里"），高德搜不到，要拆。"""
    cands = []
    if name in ALIAS:
        cands.append(ALIAS[name])
    cands.append(name)
    head = SPLIT.split(name)[0].strip()
    if head and head != name:
        cands.append(head)
    # 去掉常见后缀再试一次
    bare = re.sub(r"(景区|公园|遗址公园|博物院|博物馆|步行街|古镇|街区|"
                  r"观景平台|艺术区|文化公园)$", "", head).strip()
    if bare and bare not in cands and len(bare) >= 2:
        cands.append(bare)
    return cands


def mark_uncal(r, I):
    """标记这条坐标还是估值 —— 以后要分得清哪些已校正哪些没有。"""
    note = r[I["note"]]
    mark = "坐标未校正(高德未匹配)"
    if "坐标已用高德校正" in note:
        return
    if mark not in note:
        r[I["note"]] = (note + "；" if note else "") + mark


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只报告不改文件")
    ap.add_argument("--city", help="只处理这个城市")
    ap.add_argument("--auto-km", type=float, default=AUTO_KM)
    ap.add_argument("--accept", nargs="*", metavar="景点名",
                    help="额外接受这些可疑项（人工判断过是对的）")
    a = ap.parse_args()

    rows = list(csv.reader(io.StringIO(
        io.open(CSV, encoding="utf-8-sig").read())))
    hdr, data = rows[0], rows[1:]
    I = {c: i for i, c in enumerate(hdr)}

    todo = [r for r in data if not a.city or r[I["city"]] == a.city]
    print("待处理 %d 条%s\n" % (len(todo), ("（%s）" % a.city) if a.city else ""))

    fixed, suspect, failed, same = [], [], [], 0
    for n, r in enumerate(todo, 1):
        name, city = r[I["name"]], r[I["city"]]
        try:
            old_lng = float(r[I["lng"]]); old_lat = float(r[I["lat"]])
        except ValueError:
            old_lng = old_lat = None

        hit = None
        rejected = []
        for kw in search_name(name):
            ps = [p for p in amap.poi_search(kw, city, page_size=10)
                  if p["lng"]]
            if not ps:
                continue
            good = []
            for p in ps:
                ok, why = accept(kw, p)
                if ok:
                    good.append(p)
                else:
                    rejected.append((p["name"], why))
            if not good:
                continue
            # 排序：非站点优先（站点坐标不是景区本体），再按离原坐标近
            good.sort(key=lambda p: (
                1 if is_station(p["name"]) else 0,
                amap.km(old_lng, old_lat, p["lng"], p["lat"])
                if old_lng is not None else 0))
            hit = good[0]
            break

        if not hit:
            why = ("；".join("%s(%s)" % r for r in rejected[:2])
                   if rejected else "无结果")
            mark_uncal(r, I)
            failed.append((name, city, why))
            print("  %3d/%d  %-24s 没有可信匹配  [%s]"
                  % (n, len(todo), name, why[:40]))
            continue

        d = (amap.km(old_lng, old_lat, hit["lng"], hit["lat"])
             if old_lng is not None else 99)
        accepted = (name in CONFIRMED) or bool(a.accept and name in a.accept)
        if d <= CONFIRM_KM or accepted:
            tag = "ok"
        elif d <= a.auto_km:
            tag = "待确认"
        else:
            tag = "可疑"
        print("  %3d/%d  %-24s %-5s 差 %6.2f km  -> %s"
              % (n, len(todo), name, tag, d, hit["name"]))

        if tag == "ok":
            if d < 0.05:
                same += 1
            r[I["lng"]] = "%.6f" % hit["lng"]
            r[I["lat"]] = "%.6f" % hit["lat"]
            # 留痕：坐标来源换成高德，但 verified 不动 ——
            # 坐标准了不代表门票、停留时长这些也核实了
            r[I["source_url"]] = "高德POI:" + (hit["id"] or "")
            note = r[I["note"]]
            mark = "坐标已用高德校正"
            if mark not in note:
                r[I["note"]] = (note + "；" if note else "") + mark
            fixed.append((name, d, hit["name"]))
        else:
            mark_uncal(r, I)
            suspect.append((name, city, d, hit["name"], hit["lng"], hit["lat"],
                            hit.get("address") or ""))

    print("\n" + "=" * 62)
    print("自动校正 %d 条（其中 %d 条原本就基本准确，差 < 50m）"
          % (len(fixed), same))
    print("待确认/可疑 %d 条（移动 > %.0fkm，没动）" % (len(suspect), CONFIRM_KM))
    print("没有可信匹配 %d 条（保留原坐标）" % len(failed))

    if fixed:
        big = sorted([f for f in fixed if f[1] > 0.3], key=lambda x: -x[1])
        if big:
            print("\n--- 校正幅度最大的（原来偏得最多）---")
            for nm, d, hn in big[:12]:
                print("  %-24s 移动 %5.2f km   匹配到 %s" % (nm, d, hn))

    if suspect:
        print("\n--- 可疑，需要你判断（没有自动改）---")
        for nm, ct, d, hn, lng, lat, addr in suspect:
            print("  %s（%s）差 %.1f km" % (nm, ct, d))
            print("     高德给的是：%s  %s" % (hn, addr[:40]))
            print("     坐标 %.6f,%.6f" % (lng, lat))
    if failed:
        print("\n--- 没有可信匹配（保留原坐标）---")
        for nm, ct, why in failed:
            print("  %s（%s）" % (nm, ct))
            print("     被排除的候选：%s" % why[:70])

    if a.dry:
        print("\n--dry 模式，文件没动。")
        return 0
    if not fixed:
        print("\n没有需要写回的。")
        return 0

    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([hdr] + data)
    io.open(CSV, "w", encoding="utf-8-sig", newline="").write(buf.getvalue())
    print("\n已写回 %s（%d 条坐标更新）" % (CSV.name, len(fixed)))
    print("别忘了：python scripts/build_web.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
