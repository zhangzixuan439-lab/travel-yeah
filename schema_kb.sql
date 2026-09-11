-- 旅游攻略 · 知识库（目的地 / 景点 / 美食 / 城际交通）
-- 与 booking_rule 同库；建库：sqlite3 travel.db < data/schema_kb.sql
--
-- 设计原则：只存"年级/半年级稳定"的信息。
--   具体车次号、航班号、市内地铁公交方案、酒店实时价 —— 一律不存，实时查高德/12306。
--   写死车次号一次调图就全废。
--
-- 每张表都带三个治理字段（和 booking_rule 一致的口径）：
--   src_confidence  high=公认地标/官方名录  mid=知名但细节可能变  low=需重点核实
--   verified        0=未对过官方/榜单来源
--   last_check_date 超 180 天视为过期（餐饮比景点变得快）

DROP VIEW IF EXISTS v_kb_stale;
DROP TABLE IF EXISTS stay;
DROP TABLE IF EXISTS arrival;
DROP TABLE IF EXISTS transit;
DROP TABLE IF EXISTS route;
DROP TABLE IF EXISTS food;
DROP TABLE IF EXISTS poi;
DROP TABLE IF EXISTS destination;

-- ============ 目的地（城市 / 景区 / 古镇 / 海岛级） ============
CREATE TABLE destination (
  dest_id         TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  city            TEXT NOT NULL,
  province        TEXT NOT NULL,
  dest_type       TEXT,            -- 城市|景区|古镇|海岛|山岳|草原|沙漠
  center_lat      REAL,
  center_lng      REAL,

  -- 时间窗：推荐引擎的硬过滤条件
  best_months     TEXT,            -- "3;4;5;9;10" 分号分隔（避开 CSV 逗号）
  avoid_months    TEXT,            -- 不该去的月份（封山/极端天气/极度拥挤）
  avoid_reason    TEXT,            -- 为什么不该去，反推荐直接用这句
  suggest_days_min INTEGER,        -- 少于这个天数不值得去（含往返）
  suggest_days_max INTEGER,

  -- 偏好打分 0-100，对应用户输入的偏好权重
  tag_photo       INTEGER,         -- 出片
  tag_food        INTEGER,         -- 美食
  tag_nature      INTEGER,         -- 自然风光
  tag_culture     INTEGER,         -- 人文历史
  tag_kids        INTEGER,         -- 亲子
  tag_chill       INTEGER,         -- 躺平/慢节奏
  tag_niche       INTEGER,         -- 小众程度（越高越没人去）

  consume_level   INTEGER,         -- 1-5 消费档位
  crowd_holiday   INTEGER,         -- 1-5 法定假日拥挤度
  crowd_weekday   INTEGER,         -- 1-5 平日拥挤度
  altitude_m      INTEGER,         -- 海拔，带老人/小孩时的硬约束
  one_liner       TEXT,            -- 一句话卖点

  src_confidence  TEXT,
  verified        INTEGER NOT NULL DEFAULT 0,
  source_url      TEXT,
  last_check_date TEXT,
  note            TEXT
);

-- ============ 景点（含网红地 / 小众地标记） ============
CREATE TABLE poi (
  poi_id          TEXT PRIMARY KEY,
  dest_id         TEXT NOT NULL,
  name            TEXT NOT NULL,
  city            TEXT NOT NULL,
  poi_type        TEXT,            -- 景点|博物馆|街区|机位|自然|宗教|工业遗址|公园
  lat             REAL,
  lng             REAL,
  official_level  TEXT,            -- 5A|4A|3A|国家级博物馆|世界遗产|无

  -- 用户明确要的分类
  hot_type        TEXT,            -- 网红|小众|经典   网红=社交平台热度高，小众=本地人去游客少
  hot_note        TEXT,            -- 为什么算网红/小众

  stay_minutes    INTEGER,         -- 建议停留，行程编排的核心输入
  open_time       TEXT,            -- "08:30"
  close_time      TEXT,            -- "17:30"
  closed_day      TEXT,            -- "周一" / 空=全年开放
  last_entry      TEXT,            -- 停止入场时刻
  ticket_price    REAL,            -- -1=未知，0=免费
  booking_rule_id TEXT,            -- 关联 booking_rule.rule_id，为空表示不需预约

  -- 拍照
  photo_score     INTEGER,         -- 出片指数 0-100
  best_light      TEXT,            -- 最佳光线时段，如 "日出后1h" / "17:00-18:30"
  shoot_tip       TEXT,            -- 机位提示

  crowd_peak      TEXT,            -- 人流高峰时段，用来给避峰建议

  -- 人群适配（反推荐用）
  suit_elderly    INTEGER,         -- 0/1 适合老人
  suit_kids       INTEGER,         -- 0/1 适合小孩
  walk_km         REAL,            -- 内部步行距离
  climb_m         INTEGER,         -- 累计爬升

  why_worth       TEXT,            -- 为什么值得去，一句话
  avoid_tip       TEXT,            -- 避坑

  src_confidence  TEXT,
  verified        INTEGER NOT NULL DEFAULT 0,
  source_url      TEXT,
  last_check_date TEXT,
  note            TEXT
);

-- ============ 美食（到店名） ============
CREATE TABLE food (
  food_id         TEXT PRIMARY KEY,
  dest_id         TEXT NOT NULL,
  city            TEXT NOT NULL,
  dish_name       TEXT NOT NULL,   -- 菜品/小吃名
  store_name      TEXT,            -- 店名。为空=只是"当地要吃这个"，没指定店
  branch_note     TEXT,            -- 分店说明，如"只有总店正宗，商场分店别去"
  address         TEXT,
  lat             REAL,
  lng             REAL,

  price_per_person REAL,           -- 人均，-1=未知
  price_confidence TEXT,           -- 人均的可信度，餐饮价格变得快单列一个字段

  rating          REAL,            -- 评分。⚠ 留空 = 没有可靠来源。
                                   --   大众点评评分无开放接口、抓不到，绝不编造。
                                   --   能填的来源见 rating_source。
  rating_source   TEXT,            -- 高德|米其林|黑珍珠|必吃榜|人工实地

  -- 权威来源，这是替代小红书的关键
  list_source     TEXT,            -- 必吃榜|黑珍珠|米其林|中华老字号|地方非遗|地标老店
  list_year       INTEGER,

  queue_level     INTEGER,         -- 1-5 排队程度
  best_time       TEXT,            -- 几点去不排队
  open_time       TEXT,
  closed_day      TEXT,
  is_local_only   INTEGER,         -- 1=本地特色（非全国连锁）
  why_worth       TEXT,            -- 为什么值得吃，一句话
  avoid_tip       TEXT,            -- 避坑，如"游客街那家是假的"

  src_confidence  TEXT,
  verified        INTEGER NOT NULL DEFAULT 0,
  source_url      TEXT,
  last_check_date TEXT,
  note            TEXT
);

-- ============ 城际交通（不存车次号！） ============
CREATE TABLE route (
  route_id        TEXT PRIMARY KEY,
  from_city       TEXT NOT NULL,
  to_city         TEXT NOT NULL,
  mode            TEXT NOT NULL,   -- 高铁|动车|普速|飞机|大巴|自驾
  train_type      TEXT,            -- G|D|K/T|—  只存字头，不存具体车次
  station_from    TEXT,            -- 出发站/机场
  station_to      TEXT,

  duration_min    INTEGER,         -- 纯乘坐耗时
  price_min       REAL,            -- 票价区间下限（二等座/经济舱）
  price_max       REAL,
  frequency       TEXT,            -- 班次密度：密集|较多|少|每日1-2班

  -- 飞机的隐性成本，很多人算漏
  --
  -- ⚠ access_min / egress_min 的口径：这两个是「城市中心 ↔ 车站/机场」的**参考值**，
  --   不是某个具体用户的通勤时间 —— 库不可能知道用户住哪。
  --   前端必须标注"按市中心估算"，并允许用户用自己的数字覆盖（存在本机）。
  --   要精确值只能实时调高德路径规划，那属于在线计算不进库。
  access_min      INTEGER,         -- 市中心 -> 出发站/机场 参考耗时
  egress_min      INTEGER,         -- 到达站/机场 -> 目的地市中心 参考耗时
  buffer_min      INTEGER,         -- 安检候车预留（飞机 110，高铁 30，普速 30）
  total_min       INTEGER,         -- 门到门参考值 = duration + access + egress + buffer

  transfer_note   TEXT,            -- 是否需换乘
  book_channel    TEXT,            -- 12306|航司官网|携程
  book_tip        TEXT,            -- 抢票提示，如"节前7天放票即抢"

  src_confidence  TEXT,
  verified        INTEGER NOT NULL DEFAULT 0,
  source_url      TEXT,
  last_check_date TEXT,
  note            TEXT
);

-- ============ 市内接驳（只存粗粒度，精确换乘实时查高德） ============
-- 存的是"最近地铁站 + 步行几分钟"这种年级稳定的信息，供行程编排估算换乘成本。
-- 不存换乘方案、不存公交实时到站 —— 那些高德给得更准。
CREATE TABLE transit (
  transit_id      TEXT PRIMARY KEY,
  poi_id          TEXT NOT NULL,
  city            TEXT NOT NULL,
  mode            TEXT NOT NULL,   -- 地铁|公交|步行|打车|景区交通
  line_name       TEXT,            -- "地铁4号线"；公交填线路号
  station_name    TEXT,            -- 站名。新线开通会变，所以要留 last_check
  walk_min        INTEGER,         -- 出站后步行分钟
  taxi_min        INTEGER,         -- 打车耗时（无轨道覆盖时填这个）
  taxi_price      REAL,            -- 打车估价
  note            TEXT,

  src_confidence  TEXT,
  verified        INTEGER NOT NULL DEFAULT 0,
  source_url      TEXT,
  last_check_date TEXT
);
CREATE INDEX idx_transit_poi ON transit(poi_id);

-- ============ 到达站 -> 景点 的接驳（解决"下了车怎么去"）============
-- 与 transit 表的区别：
--   transit  = 景点 <- 最近地铁站（在城里已经安顿好之后用）
--   arrival  = 到达站 -> 具体景点（刚下火车/飞机，拖着箱子那一刻用）
-- 地铁线路与站名是年级稳定的，适合进库；实时换乘方案仍然查高德。
CREATE TABLE arrival (
  arrival_id      TEXT PRIMARY KEY,
  station_name    TEXT NOT NULL,   -- 到达站，如"南京南""上海虹桥"
  city            TEXT NOT NULL,
  to_poi_id       TEXT,            -- 关联 poi.poi_id；为空表示"去市区"这种泛指
  to_poi_name     TEXT,            -- 冗余存名字，前端不用 join
  mode            TEXT NOT NULL,   -- 地铁|公交|打车|步行|动车
  line_name       TEXT,
  transfer_note   TEXT,            -- 怎么换乘，写成一句人话
  duration_min    INTEGER,         -- 全程耗时
  price           REAL,            -- 票价或打车估价
  walk_min        INTEGER,         -- 出站后步行分钟
  note            TEXT,

  src_confidence  TEXT,
  verified        INTEGER NOT NULL DEFAULT 0,
  source_url      TEXT,
  last_check_date TEXT
);
CREATE INDEX idx_arrival_station ON arrival(station_name);
CREATE INDEX idx_arrival_city ON arrival(city);

-- ============ 住宿片区（不是单个酒店）============
-- 攻略里住宿最值钱的不是订哪家，是**住哪个片区** —— 住错片区每天多花两小时通勤。
-- 所以主键是片区，酒店名只作举例。实时房价拿不到（携程系需企业资质），
-- 只给三档区间估值 + 旺季系数。
CREATE TABLE stay (
  stay_id         TEXT PRIMARY KEY,
  dest_id         TEXT NOT NULL,
  city            TEXT NOT NULL,
  area_name       TEXT NOT NULL,   -- 片区名，如"钟楼与回民街"
  area_type       TEXT,            -- 核心景区|商业中心|交通枢纽
  lat             REAL,
  lng             REAL,

  why_here        TEXT,            -- 为什么住这，一句话
  metro_access    TEXT,            -- 地铁覆盖
  walk_to         TEXT,            -- 步行可达哪些景点

  -- 三档房价区间（元/晚，平日）
  price_eco_low   REAL, price_eco_high  REAL,
  price_mid_low   REAL, price_mid_high  REAL,
  price_high_low  REAL, price_high_high REAL,
  peak_multiplier REAL,            -- 旺季系数，国庆春节按这个乘

  example_hotels  TEXT,            -- 地标酒店举例，分号分隔
  avoid_tip       TEXT,

  src_confidence  TEXT,
  verified        INTEGER NOT NULL DEFAULT 0,
  source_url      TEXT,
  last_check_date TEXT,
  note            TEXT
);
CREATE INDEX idx_stay_city ON stay(city);

CREATE INDEX idx_poi_dest ON poi(dest_id);
CREATE INDEX idx_poi_hot  ON poi(hot_type);
CREATE INDEX idx_food_dest ON food(dest_id);
CREATE INDEX idx_food_list ON food(list_source);
CREATE INDEX idx_route_pair ON route(from_city, to_city);
CREATE INDEX idx_dest_city ON destination(city);

-- 过期/待核实：餐饮 180 天，其余 365 天
CREATE VIEW v_kb_stale AS
SELECT 'food' AS tbl, food_id AS id, city, dish_name AS name, src_confidence,
       verified, last_check_date
FROM food
WHERE verified=0 OR last_check_date IS NULL
   OR julianday('now')-julianday(last_check_date) > 180
UNION ALL
SELECT 'poi', poi_id, city, name, src_confidence, verified, last_check_date
FROM poi
WHERE verified=0 OR last_check_date IS NULL
   OR julianday('now')-julianday(last_check_date) > 365
UNION ALL
SELECT 'route', route_id, from_city||'->'||to_city, mode, src_confidence,
       verified, last_check_date
FROM route
WHERE verified=0 OR last_check_date IS NULL
   OR julianday('now')-julianday(last_check_date) > 365
UNION ALL
SELECT 'transit', transit_id, city, COALESCE(line_name,mode), src_confidence,
       verified, last_check_date
FROM transit
WHERE verified=0 OR last_check_date IS NULL
   OR julianday('now')-julianday(last_check_date) > 180
UNION ALL
SELECT 'arrival', arrival_id, city, station_name||' -> '||COALESCE(to_poi_name,'市区'),
       src_confidence, verified, last_check_date
FROM arrival
WHERE verified=0 OR last_check_date IS NULL
   OR julianday('now')-julianday(last_check_date) > 180
UNION ALL
SELECT 'stay', stay_id, city, area_name, src_confidence, verified, last_check_date
FROM stay
WHERE verified=0 OR last_check_date IS NULL
   OR julianday('now')-julianday(last_check_date) > 180;
