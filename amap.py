#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""高德 Web 服务 API 的薄封装：读 Key、限流、统一错误处理。

Key 放在项目根的 .env.local（已在 .gitignore 里，不会进仓库）：
    AMAP_KEY=你的32位key

个人认证 Key 的 QPS 有限，所以这里默认 3 QPS 串行跑，不做并发。
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://restapi.amap.com"
QPS_SLEEP = 0.35          # 约 3 QPS
_last_call = [0.0]


def load_key() -> str:
    for name in (".env.local", ".env"):
        p = ROOT / name
        if not p.exists():
            continue
        for line in io.open(p, encoding="utf-8"):
            m = re.match(r"\s*AMAP_KEY\s*=\s*(\S+)", line)
            if m:
                return m.group(1)
    raise SystemExit(
        "没找到 AMAP_KEY。请在 %s 里写一行：AMAP_KEY=你的key\n"
        "（复制 .env.example 改名即可，该文件不会进 git）" % (ROOT / ".env.local"))


KEY = None


def call(path: str, **params) -> dict:
    """调一次高德接口。自动限流；网络错误重试两次。"""
    global KEY
    if KEY is None:
        KEY = load_key()
    params = {k: v for k, v in params.items() if v not in (None, "")}
    params["key"] = KEY
    url = BASE + path + "?" + urllib.parse.urlencode(params)

    wait = QPS_SLEEP - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)

    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                _last_call[0] = time.time()
                d = json.loads(r.read().decode("utf-8"))
            if d.get("status") != "1":
                info = d.get("info", "")
                # 配额或频率问题要立刻停，继续跑只会浪费
                if any(k in info for k in ("QUOTA", "LIMIT", "DAILY", "OVER")):
                    raise SystemExit("高德返回 %s —— 配额或频率受限，先停。" % info)
                return {}
            return d
        except SystemExit:
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(1.2 * (attempt + 1))
    print("    ! 三次都失败：%s" % last_err)
    return {}


def geocode(address: str, city: str = "") -> tuple | None:
    """地址 -> (lng, lat, 格式化地址)"""
    d = call("/v3/geocode/geo", address=address, city=city)
    gs = d.get("geocodes") or []
    if not gs:
        return None
    loc = gs[0].get("location") or ""
    if "," not in loc:
        return None
    lng, lat = loc.split(",")
    return float(lng), float(lat), gs[0].get("formatted_address") or ""


def poi_search(keywords: str, city: str = "", types: str = "",
               page_size: int = 10, page: int = 1) -> list[dict]:
    """POI 搜索（v5，带 business 字段：评分、人均、营业时间）。"""
    d = call("/v5/place/text", keywords=keywords, region=city, types=types,
             show_fields="business,photos", page_size=page_size, page_num=page,
             city_limit="true")
    out = []
    for p in d.get("pois") or []:
        b = p.get("business") or {}
        loc = p.get("location") or ""
        lng = lat = None
        if "," in loc:
            a, b2 = loc.split(",")
            try:
                lng, lat = float(a), float(b2)
            except ValueError:
                pass
        out.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "type": p.get("type"),
            "typecode": p.get("typecode"),
            "address": p.get("address"),
            "district": (p.get("pname") or "") + (p.get("cityname") or "")
                        + (p.get("adname") or ""),
            "lng": lng, "lat": lat,
            "rating": _f(b.get("rating")),
            "cost": _f(b.get("cost")),
            "opentime": b.get("opentime_week") or b.get("opentime_today") or "",
            "tel": b.get("tel") or "",
        })
    return out


def route_minutes(o: tuple, d: tuple, city: str = "", mode: str = "transit") -> dict | None:
    """两点间耗时。mode: transit(公交) / driving / walking。
    返回 {minutes, distance_m, walk_m, mode}"""
    origin = "%.6f,%.6f" % (o[0], o[1])
    dest = "%.6f,%.6f" % (d[0], d[1])
    if mode == "transit":
        r = call("/v3/direction/transit/integrated", origin=origin,
                 destination=dest, city=city, strategy="0")
        ts = (r.get("route") or {}).get("transits") or []
        if ts:
            return {"minutes": round(int(ts[0]["duration"]) / 60),
                    "distance_m": int(ts[0].get("distance") or 0),
                    "walk_m": int(ts[0].get("walking_distance") or 0),
                    "mode": "公交"}
        mode = "driving"      # 太近或无公交，退回驾车
    if mode == "driving":
        r = call("/v3/direction/driving", origin=origin, destination=dest,
                 extensions="base")
        ps = (r.get("route") or {}).get("paths") or []
        if ps:
            return {"minutes": round(int(ps[0]["duration"]) / 60),
                    "distance_m": int(ps[0].get("distance") or 0),
                    "walk_m": 0, "mode": "驾车"}
    r = call("/v3/direction/walking", origin=origin, destination=dest)
    ps = (r.get("route") or {}).get("paths") or []
    if ps:
        return {"minutes": round(int(ps[0]["duration"]) / 60),
                "distance_m": int(ps[0].get("distance") or 0),
                "walk_m": int(ps[0].get("distance") or 0), "mode": "步行"}
    return None


def _f(v):
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def km(lng1, lat1, lng2, lat2) -> float:
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


if __name__ == "__main__":
    # 自检
    print("Key 长度:", len(load_key()))
    g = geocode("故宫博物院", "北京")
    print("地理编码:", g)
    ps = poi_search("沙茶面", "厦门", types="050000", page_size=3)
    for p in ps:
        print("  %-24s %.6f,%.6f  rating=%s cost=%s"
              % (p["name"], p["lng"], p["lat"], p["rating"], p["cost"]))
    r = route_minutes((116.397128, 39.916527), (116.407387, 39.904179), "北京")
    print("路径:", r)
