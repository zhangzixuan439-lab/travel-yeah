-- 旅游攻略 · 预约规则表
-- SQLite 本地库，字段与 data/booking_rules.csv 一一对应
-- 建库: sqlite3 travel.db < data/schema.sql
-- 导入: sqlite3 travel.db -cmd ".mode csv" ".import --skip 1 data/booking_rules.csv booking_rule"

DROP VIEW IF EXISTS v_verify_priority;
DROP VIEW IF EXISTS v_stale_rule;
DROP TABLE IF EXISTS booking_rule;

CREATE TABLE booking_rule (
  rule_id           TEXT PRIMARY KEY,           -- BK001
  poi_name          TEXT NOT NULL,              -- 景区/场馆名，与 POI 表 join 的自然键
  city              TEXT NOT NULL,
  province          TEXT NOT NULL,
  category          TEXT,                       -- 博物馆|古迹|自然景区|高校|主题公园|宗教场所|纪念馆

  need_booking      INTEGER NOT NULL DEFAULT 1, -- 1=需预约 0=不需（不需的也留库，拥挤度预警仍要用）

  -- 预约渠道
  platform_name     TEXT,
  platform_type     TEXT,                       -- 官方小程序|官方公众号|官网|第三方授权|景区现场
  platform_url      TEXT,

  -- 放票规则：倒计时的核心三字段
  advance_days      INTEGER DEFAULT -1,         -- 提前天数，-1=未知必须人工核实
  release_time      TEXT DEFAULT '-1',          -- 放票时刻 HH:MM，-1 或空=未知
  release_mode      TEXT,                       -- fixed_time=定点放票 | rolling=窗口内随时可约 | onsite=现场取号
  time_slot         INTEGER DEFAULT 0,          -- 1=分时段入园
  daily_quota       INTEGER,                    -- 每日限额，NULL=未公开（不要瞎填）

  -- 抢票难度
  difficulty        INTEGER,                    -- 1=不用抢 2=提前1-2天够 3=开票当天 4=开票即抢 5=秒杀级
  sellout_speed     TEXT,                       -- seckill|minutes|hours|relaxed

  -- 实名要求
  need_id_card      INTEGER DEFAULT 0,
  need_companion_id INTEGER DEFAULT 0,          -- 需同行人全部实名，影响能否代订

  free_or_paid      TEXT,                       -- free|paid
  ticket_price      REAL DEFAULT -1,            -- -1=未知

  -- 兜底：反推荐只说"不该去"没用，必须给替代
  backup_plan       TEXT,
  backup_poi        TEXT,
  peak_note         TEXT,                       -- 旺季/季节性特殊规则

  -- 数据治理：这张表是人工维护的，血缘必须留痕
  src_confidence    TEXT,                       -- high|mid|low 初始录入可信度
  verified          INTEGER NOT NULL DEFAULT 0, -- 0=未核实 1=已对过官方渠道
  source_url        TEXT,
  last_check_date   TEXT,                       -- YYYY-MM-DD，超 90 天前端标"规则可能已变"
  note              TEXT
);

CREATE INDEX idx_br_city ON booking_rule(city);
CREATE INDEX idx_br_name ON booking_rule(poi_name);
CREATE INDEX idx_br_diff ON booking_rule(difficulty DESC);

-- 规则过期视图：前端据此打"待核实"角标
CREATE VIEW v_stale_rule AS
SELECT rule_id, poi_name, city, difficulty, verified, last_check_date, note
FROM booking_rule
WHERE need_booking = 1
  AND ( verified = 0
     OR advance_days < 0
     OR last_check_date IS NULL
     OR julianday('now') - julianday(last_check_date) > 90 )
ORDER BY difficulty DESC, city;

-- 核实优先级：难度高且信息缺口大的先查，人工排期照这个来
CREATE VIEW v_verify_priority AS
SELECT rule_id, poi_name, city, difficulty, src_confidence,
       (CASE WHEN advance_days < 0 THEN 2 ELSE 0 END)
     + (CASE WHEN release_time IN ('-1','') OR release_time IS NULL THEN 1 ELSE 0 END)
     + (CASE WHEN src_confidence = 'low' THEN 2
             WHEN src_confidence = 'mid' THEN 1 ELSE 0 END) AS gap_score
FROM booking_rule
WHERE need_booking = 1 AND verified = 0
ORDER BY difficulty DESC, gap_score DESC;
