#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""预约倒计时 —— 纯规则实现，零 AI 零爬虫。

给定游览日期和景区，回答三件事：
  1) 还没开票 -> 距开票还有几天、几点抢
  2) 今天开票 -> 立刻行动，几点、要备什么
  3) 已过放票日 -> 按难度判断还有没有戏，没戏就给替代方案

用法:
  python scripts/countdown.py --date 2026-10-01 --poi 故宫 天安门 国家博物馆
  python scripts/countdown.py --date 2026-10-01 --city 北京
  python scripts/countdown.py --date 2026-10-01 --city 北京 --ics 抢票提醒.ics
  python scripts/countdown.py --verify-list          # 待核实清单，人工排期用
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

if sys.platform == "win32":  # 控制台按 UTF-8 输出，避免中文乱码
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "booking_rules.csv"

INT_COLS = {"need_booking", "advance_days", "time_slot", "daily_quota",
            "difficulty", "need_id_card", "need_companion_id", "verified"}

WEEKDAY = ["一", "二", "三", "四", "五", "六", "日"]

# 状态 -> (排序权重, 图标, 标题)。权重小的排前面，越紧急越靠上
STATUS_META = {
    "ACTION_TODAY":   (0, "[!]", "今天开抢"),
    "MISSED":         (1, "[x]", "已过放票日"),
    "RELEASED_TODAY": (2, "[>]", "今天已放票"),
    "BOOKABLE_NOW":   (3, "[v]", "现在可约"),
    "WAITING":        (4, "[~]", "等待开票"),
    "UNKNOWN":        (5, "[?]", "规则未知"),
    "ONSITE":         (6, "[@]", "现场取号"),
    "NO_BOOKING":     (7, "[o]", "无需预约"),
    "PAST":           (8, "[-]", "日期已过"),
}


def load_rules(path: Path = CSV_PATH) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, str):
                r[k] = v.strip()
        for k in INT_COLS:
            v = (r.get(k) or "").strip()
            r[k] = int(v) if v.lstrip("-").isdigit() else None
    return rows


def parse_hhmm(s):
    if not s or s in ("-1", ""):
        return None
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def judge(rule: dict, visit: date, now: datetime) -> dict:
    """核心状态机。返回 status / 开票时刻 / 文案行。"""
    today = now.date()
    adv = rule["advance_days"]
    mode = rule.get("release_mode") or ""
    rt = parse_hhmm(rule.get("release_time"))
    diff = rule["difficulty"] or 0
    out = {"status": "UNKNOWN", "open_dt": None, "lines": []}

    def fin(status, *lines):
        out["status"] = status
        out["lines"] = [x for x in lines if x]
        return out

    if rule["need_booking"] == 0:
        return fin("NO_BOOKING", rule.get("peak_note") or "开放式景区，直接去")
    if visit < today:
        return fin("PAST", "游览日期早于今天")
    if mode == "onsite":
        return fin("ONSITE", "现场取号，无线上预约")
    if adv is None or adv < 0:
        chan = rule.get("platform_name") or "未知"
        url = (" " + rule["platform_url"]) if rule.get("platform_url") else ""
        return fin("UNKNOWN",
                   "本条规则的提前天数尚未核实，算不出倒计时",
                   "请先核对官方渠道：" + chan + url)

    open_date = visit - timedelta(days=adv)
    open_dt = datetime.combine(open_date, rt or time(9, 0))
    out["open_dt"] = open_dt
    days_to_open = (open_date - today).days

    prep = []
    if rule["need_id_card"] == 1:
        prep.append("身份证号")
    if rule["need_companion_id"] == 1:
        prep.append("同行人全部实名信息")
    prep_txt = ("，提前备好" + "、".join(prep)) if prep else ""

    if mode == "rolling":
        if days_to_open > 0:
            return fin("WAITING",
                       "%s 起可约（提前 %d 天开窗），还有 %d 天"
                       % (open_date.strftime("%m-%d"), adv, days_to_open),
                       "窗口期内随时可约，不用掐点" + prep_txt)
        left = (visit - today).days
        tip = "难度较高，建议今天就约掉" if diff >= 4 else "尽快约掉"
        return fin("BOOKABLE_NOW",
                   "预约窗口已开（%s 起），距游览还有 %d 天"
                   % (open_date.strftime("%m-%d"), left),
                   tip + prep_txt)

    # fixed_time：定点放票，唯一"错过就真没有"的模式
    if days_to_open > 0:
        if diff >= 4:
            tip = "开票即抢，务必设闹钟，提前登录" + (
                "并备好" + "、".join(prep) if prep else "")
        else:
            tip = "到点约即可" + prep_txt
        # 放票时刻未核实时不能假装知道，否则用户会按假时刻去等
        when = (open_dt.strftime("%m-%d %H:%M") if rt
                else open_date.strftime("%m-%d") + " 当天（放票时刻待核实）")
        return fin("WAITING",
                   "开票时间 %s，还有 %d 天" % (when, days_to_open),
                   tip)
    if days_to_open == 0:
        if rt and now.time() < rt:
            hrs = (open_dt - now).total_seconds() / 3600
            return fin("ACTION_TODAY",
                       "今天 %s 开票，距现在 %.1f 小时" % (rt.strftime("%H:%M"), hrs),
                       "现在就登录 " + (rule.get("platform_name") or "官方渠道") + prep_txt)
        return fin("RELEASED_TODAY",
                   "今天已放票（%s）" % (rule.get("release_time") or "时刻未核实"),
                   "立刻去查余量，售罄快的话可蹲退票")

    # today > open_date：错过放票日，按难度分级判断还有没有戏
    late = -days_to_open
    head = "放票日为 %s，已过 %d 天" % (open_date.strftime("%m-%d"), late)
    if diff <= 2:
        return fin("MISSED", head, "该馆通常不紧张，大概率仍有余票，直接去查即可")
    if diff == 3:
        return fin("MISSED", head, "可能还有余票，尽快查；同时留意退票")
    return fin("MISSED", head, "难度高，基本无票 —— 建议直接走备用方案")


def match(rules, keys, city, show_all):
    if show_all:
        return rules
    hit = []
    for r in rules:
        if city and r["city"] != city and r["province"] != city:
            continue
        if keys:
            name = r["poi_name"]
            if not any(k in name or name in k for k in keys):
                continue
        hit.append(r)
    return hit


def render(rules, visit, now):
    pairs = [(r, judge(r, visit, now)) for r in rules]
    pairs.sort(key=lambda p: (STATUS_META[p[1]["status"]][0],
                              -(p[0]["difficulty"] or 0), p[0]["rule_id"]))
    return pairs


def print_report(pairs, visit, now):
    print("\n游览日期 %s（周%s） | 当前 %s | 共 %d 个地点\n"
          % (visit.strftime("%Y-%m-%d"), WEEKDAY[visit.weekday()],
             now.strftime("%Y-%m-%d %H:%M"), len(pairs)))
    cur = None
    for rule, v in pairs:
        st = v["status"]
        if st != cur:
            print("-" * 58)
            print("%s %s\n" % (STATUS_META[st][1], STATUS_META[st][2]))
            cur = st
        stars = "*" * (rule["difficulty"] or 0)
        print("  %s（%s）  难度 %s" % (rule["poi_name"], rule["city"], stars or "-"))
        for line in v["lines"]:
            print("    " + line)
        if st == "MISSED" and (rule.get("backup_plan") or rule.get("backup_poi")):
            poi = rule.get("backup_poi") or ""
            alt = rule.get("backup_plan") or ""
            sep = "  " if poi and alt else ""
            print("    -> 替代：" + poi + sep + alt)
        if rule["verified"] == 0 and rule["need_booking"] == 1:
            print("    [待核实] 置信度 %s，出行前请对一遍官方渠道"
                  % (rule.get("src_confidence") or "?"))
        print()
    counts = {}
    for _, v in pairs:
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    tally = "  ".join("%s %d" % (STATUS_META[k][2], n) for k, n in
                      sorted(counts.items(), key=lambda x: STATUS_META[x[0]][0]))
    print("-" * 58)
    print("汇总：" + tally + "\n")


def esc(s: str) -> str:
    return (s.replace("\\", "\\\\").replace(";", "\\;")
             .replace(",", "\\,").replace("\n", "\\n"))


def fold(line: str) -> str:
    """RFC5545 行折叠：按 UTF-8 字节 75 上限切，续行前置一个空格。"""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        limit = 75 if not out else 74
        if len(cur) + len(b) > limit:
            out.append(cur.decode("utf-8"))
            cur = b
        else:
            cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def build_ics(pairs, visit, now):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//travel-planner//booking-countdown//CN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:" + esc("抢票提醒 " + visit.strftime("%Y-%m-%d"))]
    n = 0
    for rule, v in pairs:
        if v["status"] not in ("WAITING", "ACTION_TODAY") or not v["open_dt"]:
            continue
        n += 1
        start = v["open_dt"] - timedelta(minutes=10)
        uid = hashlib.md5(("%s|%s" % (rule["rule_id"], visit)).encode()).hexdigest()
        stars = "*" * (rule["difficulty"] or 0)
        parts = ["游览日 " + visit.strftime("%Y-%m-%d"),
                 "渠道 " + (rule.get("platform_name") or "待核实")]
        if stars:
            parts.append("难度 " + stars)
        if rule["need_id_card"] == 1:
            parts.append("需身份证号")
        if rule["need_companion_id"] == 1:
            parts.append("需同行人实名")
        if rule.get("backup_poi"):
            parts.append("备用 " + rule["backup_poi"])
        if rule["verified"] == 0:
            parts.append("规则未核实，请对官方渠道")
        summary = "抢票 %s（%s 游览）" % (rule["poi_name"], visit.strftime("%m-%d"))
        lines += ["BEGIN:VEVENT",
                  "UID:" + uid + "@travel-planner",
                  "DTSTAMP:" + now.strftime("%Y%m%dT%H%M%S"),
                  "DTSTART:" + start.strftime("%Y%m%dT%H%M%S"),
                  "DTEND:" + (start + timedelta(minutes=20)).strftime("%Y%m%dT%H%M%S"),
                  fold("SUMMARY:" + esc(summary)),
                  fold("DESCRIPTION:" + esc(" / ".join(parts)))]
        if rule.get("platform_url"):
            lines.append(fold("URL:" + rule["platform_url"]))
        lines += ["BEGIN:VALARM", "TRIGGER:-PT10M", "ACTION:DISPLAY",
                  "DESCRIPTION:" + esc(rule["poi_name"] + " 即将放票"),
                  "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n", n


def gap_score(r) -> int:
    s = 2 if (r["advance_days"] or -1) < 0 else 0
    s += 0 if parse_hhmm(r.get("release_time")) else 1
    s += {"low": 2, "mid": 1}.get(r.get("src_confidence"), 0)
    return s


def print_verify_list(rules):
    todo = [r for r in rules if r["need_booking"] == 1 and r["verified"] == 0]
    todo.sort(key=lambda r: (-(r["difficulty"] or 0), -gap_score(r), r["rule_id"]))
    print("\n待核实 %d 条（难度高、缺口大的排前面，照这个顺序查官方渠道）\n" % len(todo))
    print("ID      难度   缺口  景区 / 渠道 / 缺什么")
    print("-" * 74)
    for r in todo:
        miss = []
        if (r["advance_days"] or -1) < 0:
            miss.append("提前天数")
        if not parse_hhmm(r.get("release_time")):
            miss.append("放票时刻")
        print("%-7s %-5s %-4d %s（%s） | %s | 缺 %s"
              % (r["rule_id"], "*" * (r["difficulty"] or 0), gap_score(r),
                 r["poi_name"], r["city"],
                 r.get("platform_name") or "渠道未知",
                 "、".join(miss) or "仅需复核"))
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="预约倒计时（纯规则）")
    ap.add_argument("--date", help="游览日期 YYYY-MM-DD")
    ap.add_argument("--poi", nargs="*", help="景区名，支持简称模糊匹配")
    ap.add_argument("--city", help="按城市或省份筛选")
    ap.add_argument("--all", action="store_true", help="全表")
    ap.add_argument("--ics", help="导出日历文件路径")
    ap.add_argument("--verify-list", action="store_true", help="输出待核实清单")
    ap.add_argument("--csv", default=str(CSV_PATH), help="规则表路径")
    a = ap.parse_args()

    rules = load_rules(Path(a.csv))
    if a.verify_list:
        print_verify_list(rules)
        return 0
    if not a.date:
        ap.error("需要 --date，或用 --verify-list 看待核实清单")
    try:
        visit = datetime.strptime(a.date, "%Y-%m-%d").date()
    except ValueError:
        ap.error("日期格式应为 YYYY-MM-DD，收到 " + repr(a.date))
    if not (a.poi or a.city or a.all):
        ap.error("需要 --poi / --city / --all 之一")

    hit = match(rules, a.poi, a.city, a.all)
    if not hit:
        print("没有匹配到任何地点。用 --all 看全表，或换个关键词。")
        return 1

    now = datetime.now()
    pairs = render(hit, visit, now)
    print_report(pairs, visit, now)

    if a.ics:
        text, n = build_ics(pairs, visit, now)
        if n:
            Path(a.ics).write_text(text, encoding="utf-8", newline="")
            print("已写入 %s：%d 条开票提醒（各提前 10 分钟响铃），导入手机日历即可\n"
                  % (a.ics, n))
        else:
            print("没有处于「等待开票 / 今天开抢」状态的地点，未生成日历\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
