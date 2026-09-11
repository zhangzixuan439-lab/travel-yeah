/**
 * 把一条线路导出成单页 HTML（蓝白风格，可直接双击打开或发给别人）。
 *
 * 用法:  node scripts/export_guide.js <出发地> <目的地> [天数]
 * 例:    node scripts/export_guide.js 北京 厦门 4
 * 产物:  exports/<出发地>-<目的地>-攻略.html
 *
 * 行程生成直接复用 index.html 里的 buildPlan —— 不另写一套，
 * 否则网页端和导出版会算出不一样的行程。
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const [FROM, TO, DAYS_ARG] = process.argv.slice(2);
if (!FROM || !TO) {
  console.error('用法: node scripts/export_guide.js <出发地> <目的地> [天数]');
  process.exit(1);
}

/* ---------- 用最小 stub 把 index.html 的逻辑跑起来 ---------- */
global.window = {};
eval(fs.readFileSync(path.join(ROOT, 'data.js'), 'utf8'));
const mem = {};
global.localStorage = {
  getItem: k => (k in mem ? mem[k] : null),
  setItem: (k, v) => { mem[k] = v; },
  removeItem: k => { delete mem[k]; },
};
global.location = { search: '' };
const els = {};
const mkEl = id => (els[id] = {
  id, innerHTML: '', textContent: '', value: '', scrollTop: 0, style: {},
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  addEventListener() {}, querySelectorAll: () => [], closest: () => null,
  focus() {}, select() {},
});
global.document = {
  getElementById: id => els[id] || mkEl(id),
  createElement: () => mkEl('t'), body: mkEl('body'), addEventListener() {},
};
global.navigator = { clipboard: null };
global.confirm = () => true;

const src = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')
  .match(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g).pop()
  .replace(/<\/?script[^>]*>/g, '')
  .replace(/if\(!DATA\.rules\.length\)\{[\s\S]*?\}else init\(\);/,
    'module.exports={buildPlan,poisOf,foodsOf,staysOf,resolveDest,cityOf,' +
    'tripMin,mins,hm,money,yuan,stars,seasonState,isPeak,modeGroup,' +
    'transitOf,transitLine,sunsetMin,monthNow,DATA};');
const mod = { exports: {} };
new Function('module', 'window', 'location', 'localStorage', 'document',
             'navigator', 'URLSearchParams', 'confirm', src)
  (mod, global.window, global.location, global.localStorage, global.document,
   global.navigator, URLSearchParams, global.confirm);
const M = mod.exports, D = M.DATA;

const dest = M.resolveDest(TO);
const CITY = M.cityOf(TO);
const DAYS = parseInt(DAYS_ARG, 10) ||
  Math.max(2, (dest ? dest.suggest_days_min : 2) + 1);

const res = M.buildPlan(FROM, TO, DAYS);
if (!res.plan.length) {
  console.error('排不出行程：' + FROM + ' → ' + TO + '。检查库里有没有这条线路和景点。');
  process.exit(1);
}

/* ---------- 工具 ---------- */
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');
const ICON = { trip: '🚄', poi: '📍', food: '🍜', move: '🚇', free: '🕐' };
const KIND = { trip: '交通', poi: '景点', food: '吃饭', move: '转场', free: '空档' };
const today = new Date().toISOString().slice(0, 10);

const routes = (D.routes || []).filter(r => r.from_city === FROM && r.to_city === TO)
  .sort((a, b) => M.tripMin(a) - M.tripMin(b));
const stays = M.staysOf(TO).slice().sort((a, b) => {
  const o = { '核心景区': 0, '商业中心': 1, '交通枢纽': 2 };
  return (o[a.area_type] ?? 3) - (o[b.area_type] ?? 3) ||
         (a.price_mid_low || 0) - (b.price_mid_low || 0);
});
const foods = M.foodsOf(TO);
const pois = M.poisOf(TO);
const arrivals = (D.arrivals || []).filter(a => a.city === CITY);
const rules = (D.rules || []).filter(r => r.city === CITY && r.need_booking === 1);
const peak = M.isPeak();
const spend = res.spend;
const total = spend.train + spend.hotel + spend.ticket + spend.food + spend.local;

/* ---------- 各区块 ---------- */
function planBlocks() {
  return res.plan.map(d => {
    const rows = d.items.map(it => {
      const cls = it.kind === 'trip' ? 'r-trip' :
                  it.kind === 'food' ? 'r-food' :
                  (it.kind === 'move' || it.kind === 'free') ? 'r-move' : '';
      return `<tr class="${cls}">
        <td class="mono nowrap">${M.hm(it.s)}–${M.hm(it.e)}</td>
        <td class="nowrap">${ICON[it.kind]} ${KIND[it.kind]}</td>
        <td><b>${esc(it.name)}</b>${it.meal ? ` <span class="tag tag-g">${it.meal}</span>` : ''}${
          it.book ? ' <span class="tag tag-y">需预约</span>' : ''}${
          it.far ? ' <span class="tag tag-o">较远</span>' : ''}</td>
        <td class="note-cell">${esc(it.note).replace(/\n/g, '<br>')}</td>
      </tr>`;
    }).join('');
    const span = d.items.length
      ? `${M.hm(d.items[0].s)} – ${M.hm(d.items[d.items.length - 1].e)}`
      : '';
    return `<h3>DAY ${d.day}　<span class="h3-sub">${esc(d.title)}　${span}</span></h3>
      <table><thead><tr><th style="width:104px">时段</th>
        <th style="width:76px">类型</th><th style="width:160px">地点</th>
        <th>说明</th></tr></thead><tbody>${rows}</tbody></table>`;
  }).join('');
}

function routeRows() {
  return routes.map((r, i) => {
    const night = r.mode === '普速' && (r.duration_min || 0) >= 360;
    const tags = [
      i === 0 ? '<span class="tag tag-g">车上最短</span>' : '',
      night ? '<span class="tag tag-b">夜车</span>' : '',
    ].join('');
    return `<tr>
      <td><b>${esc(r.mode)}</b>${r.train_type && r.train_type !== '—'
        ? ' ' + esc(r.train_type) + '字头' : ''}${tags}</td>
      <td class="mono nowrap">${M.mins(r.duration_min)}</td>
      <td class="mono nowrap">${M.money(r.price_min, r.price_max)}</td>
      <td class="nowrap">${esc(r.station_from)} → ${esc(r.station_to)}</td>
      <td>${esc(r.frequency || '')}${
        r.transfer_note && r.transfer_note !== '直达'
          ? `<br><span class="warn-inline">⚠ ${esc(r.transfer_note)}</span>` : ''}${
        night ? '<br>卧铺省一晚酒店，白天不占用' : ''}</td>
    </tr>`;
  }).join('');
}

function arrivalRows() {
  const by = {};
  arrivals.forEach(a => { (by[a.station_name] = by[a.station_name] || []).push(a); });
  return Object.keys(by).map(st => {
    const rows = by[st].map(a => `<tr>
      <td class="nowrap">${esc(a.to_poi_name === '—' ? '市区' : a.to_poi_name)}</td>
      <td class="nowrap">${esc(a.mode)}${a.line_name && a.line_name !== '—'
        ? '<br><span class="dim">' + esc(a.line_name) + '</span>' : ''}</td>
      <td class="mono nowrap">${a.duration_min ? M.mins(a.duration_min) : '—'}</td>
      <td class="mono nowrap">${a.price ? '¥' + a.price : '—'}</td>
      <td>${esc(a.transfer_note || '')}${a.walk_min
        ? `　<b>出站步行 ${a.walk_min}min</b>` : ''}${
        a.note ? `<br><span class="warn-inline">${esc(a.note)}</span>` : ''}</td>
    </tr>`).join('');
    return `<h4>${esc(st)}站出发</h4>
      <table><thead><tr><th style="width:150px">去哪</th>
      <th style="width:110px">方式</th><th style="width:70px">耗时</th>
      <th style="width:64px">票价</th><th>怎么走</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }).join('');
}

function stayRows() {
  return stays.map(s => {
    const m = peak ? (s.peak_multiplier || 1.8) : 1;
    const rng = (a, b) => a == null ? '—'
      : `¥${Math.round(a * m)}–${Math.round(b * m)}`;
    const tagc = s.area_type === '核心景区' ? 'tag-g'
      : s.area_type === '商业中心' ? 'tag-o' : 'tag-y';
    return `<tr>
      <td><b>${esc(s.area_name)}</b><br>
        <span class="tag ${tagc}">${esc(s.area_type)}</span></td>
      <td>${esc(s.why_here || '')}<br>
        <span class="dim">🚇 ${esc(s.metro_access || '')}</span>${
        s.walk_to ? `<br><span class="dim">🚶 ${esc(s.walk_to)}</span>` : ''}</td>
      <td class="mono nowrap">经济 ${rng(s.price_eco_low, s.price_eco_high)}<br>
        舒适 ${rng(s.price_mid_low, s.price_mid_high)}<br>
        高档 ${rng(s.price_high_low, s.price_high_high)}</td>
      <td>${s.example_hotels ? esc(s.example_hotels) : '—'}</td>
      <td>${s.avoid_tip ? `<span class="warn-inline">${esc(s.avoid_tip)}</span>` : '—'}</td>
    </tr>`;
  }).join('');
}

/* 每类来源的依据要写清楚：哪些能查证、哪些是判断 */
const FOOD_SRC = {
  '中华老字号': ['官方名录', '商务部认定并公布的「中华老字号」名录，公开可查。'
    + '店铺存在性可查证，但具体门店的人均与营业时间仍需现场确认。'],
  '米其林': ['官方榜单', '米其林指南中国官网公布，含菜系与价位区间。'],
  '黑珍珠': ['官方榜单', '美团发布的黑珍珠餐厅指南，官网有按城市按钻级的完整名单。'],
  '必吃榜': ['官方榜单', '美团大众点评每年发布。榜单页可查，但完整名单媒体报道'
    + '只给数字不给列表，需逐城市从榜单页抄。'],
  '地标老店': ['长期口碑判断', '本地长期公认的店，依据是广泛口碑而<b>不是官方名录</b>。'
    + '店铺确凿存在，但「是不是最好」属于主观判断。'],
  '地方特色': ['只指明吃什么', '没有指定具体店铺，只说当地该吃这道菜。'
    + '需要自己就近找店。'],
  '高德POI': ['接口拉取', '用高德 Web 服务 API 按本地菜品搜索得到，'
    + '<b>评分与人均是高德自己的数据（不是大众点评）</b>，营业时间也来自高德。'
    + '优点是量大且数字真实；缺点是<b>没有避坑信息</b> —— '
    + '哪家是游客店、哪家要先谈价，接口不会告诉你。'],
};

function foodSourceTable() {
  const used = [...new Set(foods.map(f => f.list_source))];
  const order = ['中华老字号', '米其林', '黑珍珠', '必吃榜',
                 '地标老店', '地方特色', '高德POI'];
  const rows = order.filter(k => used.includes(k)).map(k => {
    const n = foods.filter(f => f.list_source === k).length;
    const [kind, desc] = FOOD_SRC[k] || ['—', ''];
    const tagc = kind.includes('官方') ? 'tag-g' : 'tag-y';
    return `<tr>
      <td><b>${esc(k)}</b></td>
      <td class="nowrap"><span class="tag ${tagc}">${esc(kind)}</span></td>
      <td class="mono nowrap">${n} 条</td>
      <td>${desc}</td>
    </tr>`;
  }).join('');
  const missing = order.filter(k => !used.includes(k) &&
    ['米其林', '黑珍珠', '必吃榜'].includes(k));
  return `<table><thead><tr><th style="width:112px">来源</th>
    <th style="width:104px">性质</th><th style="width:64px">本页</th>
    <th>依据与限度</th></tr></thead><tbody>${rows}</tbody></table>${
    missing.length ? `<p class="dim" style="margin-top:8px">
      还没入库的来源：<b>${missing.join('、')}</b> ——
      这三类都有官方公开名单（米其林与黑珍珠官网、必吃榜榜单页），
      但需要逐城市抄进 <code>data/foods.csv</code>，目前还没做。</p>` : ''}`;
}

function foodBlocks() {
  const order = ['中华老字号', '米其林', '黑珍珠', '必吃榜',
                 '地标老店', '地方特色', '高德POI'];
  const gp = {};
  foods.forEach(f => { (gp[f.list_source] = gp[f.list_source] || []).push(f); });
  const keys = order.concat(Object.keys(gp))
    .filter((v, i, a) => a.indexOf(v) === i && gp[v]);
  const CONF = { high: ['tag-g', '高'], mid: ['tag-y', '中'], low: ['tag-o', '低'] };
  return keys.map(src => {
    const rows = gp[src].slice()
      .sort((a, b) => (b.queue_level || 0) - (a.queue_level || 0))
      .map(f => {
        const c = CONF[f.src_confidence] || ['tag-y', '?'];
        return `<tr>
        <td><b>${esc(f.store_name && f.store_name !== '—'
          ? f.store_name : '（未指定店铺）')}</b>
          <span class="tag ${c[0]}" title="录入依据的可信度">依据${c[1]}</span>${
          f.branch_note ? `<br><span class="dim">${esc(f.branch_note)}</span>` : ''}</td>
        <td class="nowrap">${esc(f.dish_name)}</td>
        <td class="mono nowrap">${f.price_per_person > 0
          ? '约 ¥' + f.price_per_person : '待核实'}<br>
          <span class="dim">${f.rating ? esc(f.rating) + ' 分（' +
            esc(f.rating_source || '来源未注') + '）' : '无评分'}</span></td>
        <td class="nowrap">${f.queue_level ? M.stars(f.queue_level) : '—'}${
          f.best_time ? `<br><span class="dim">${esc(f.best_time)}</span>` : ''}</td>
        <td>${esc(f.why_worth || '')}${f.avoid_tip
          ? `<br><span class="warn-inline">⚠ ${esc(f.avoid_tip)}</span>` : ''}${
          f.note ? `<br><span class="dim">${esc(f.note)}</span>` : ''}</td>
      </tr>`;
      }).join('');
    const [kind] = FOOD_SRC[src] || ['—'];
    return `<h4>${esc(src)}　<span class="dim">${gp[src].length} 条 · ${esc(kind)}</span></h4>
      <table><thead><tr><th style="width:168px">店名</th>
      <th style="width:96px">招牌</th><th style="width:104px">人均 / 评分</th>
      <th style="width:88px">排队</th><th>为什么吃 / 避坑</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }).join('');
}

function poiBlocks() {
  const HOT = { '网红': ['tag-o', '社交平台热度高，人也最多'],
                '小众': ['tag-g', '游客少，本地人常去'],
                '经典': ['tag-y', '到了就该去的标准项'] };
  return ['网红', '小众', '经典'].map(ht => {
    const g = pois.filter(p => p.hot_type === ht)
      .sort((a, b) => (b.photo_score || 0) - (a.photo_score || 0));
    if (!g.length) return '';
    const rows = g.map(p => {
      const tr = M.transitOf(p.poi_id);
      return `<tr>
        <td><b>${esc(p.name)}</b>${p.booking_rule_id
          ? ' <span class="tag tag-y">需预约</span>' : ''}</td>
        <td class="mono nowrap">${M.mins(p.stay_minutes)}</td>
        <td class="mono nowrap">${p.ticket_price === 0 ? '免费'
          : p.ticket_price > 0 ? '¥' + p.ticket_price : '待核实'}</td>
        <td class="mono nowrap">${p.photo_score || '—'}</td>
        <td>${esc(p.why_worth || '')}${
          p.best_light ? `<br><span class="dim">📷 ${esc(p.best_light)}</span>` : ''}${
          tr.length ? `<br><span class="dim">${esc(M.transitLine(tr[0])
            .replace(/<[^>]+>/g, ''))}</span>` : ''}${
          p.avoid_tip ? `<br><span class="warn-inline">⚠ ${esc(p.avoid_tip)}</span>` : ''}</td>
      </tr>`;
    }).join('');
    return `<h4><span class="tag ${HOT[ht][0]}">${ht}</span>　${g.length} 处
      <span class="dim">${HOT[ht][1]}</span></h4>
      <table><thead><tr><th style="width:168px">名称</th>
      <th style="width:74px">停留</th><th style="width:74px">门票</th>
      <th style="width:56px">出片</th><th>为什么去 / 避坑</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }).join('');
}

function ruleRows() {
  if (!rules.length) return '<p class="dim">这个城市库里没有需要预约的项目。</p>';
  return `<table><thead><tr><th style="width:150px">项目</th>
    <th style="width:96px">提前天数</th><th style="width:90px">放票时刻</th>
    <th style="width:80px">抢票难度</th><th>渠道 / 备用方案</th></tr></thead><tbody>${
    rules.slice().sort((a, b) => (b.difficulty || 0) - (a.difficulty || 0))
      .map(r => `<tr>
        <td><b>${esc(r.poi_name)}</b></td>
        <td class="mono">${r.advance_days >= 0 ? '提前 ' + r.advance_days + ' 天'
          : '<span class="warn-inline">未核实</span>'}</td>
        <td class="mono">${r.release_time && r.release_time !== '-1'
          ? esc(r.release_time) : '—'}</td>
        <td>${r.difficulty ? M.stars(r.difficulty) : '—'}</td>
        <td>${esc(r.platform_name || '')}${r.backup_plan
          ? `<br><span class="dim">备用：${esc(r.backup_plan)}</span>` : ''}${
          r.verified !== 1 ? '<br><span class="warn-inline">规则未核实，出行前务必对官方渠道</span>' : ''}</td>
      </tr>`).join('')}</tbody></table>`;
}

const ss = M.seasonState(dest);

/* ---------- 组装 ---------- */
const html = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>${esc(FROM)} → ${esc(TO)} 攻略</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:#f1f5f9;color:#1f2937;line-height:1.65;-webkit-font-smoothing:antialiased}
.banner{background:linear-gradient(135deg,#1a365d 0%,#1d4ed8 50%,#3b82f6 100%);
  color:#fff;padding:30px 34px}
.banner h1{font-size:26px;font-weight:600;letter-spacing:.5px}
.banner .sub{font-size:13px;opacity:.92;margin-top:6px}
.banner .meta{font-size:12px;opacity:.85;margin-top:10px}
.wrap{max-width:1080px;margin:0 auto;padding:22px}
.card{background:#fff;border-radius:12px;box-shadow:0 1px 6px rgba(0,0,0,.05);
  padding:22px 24px;margin-bottom:18px}
h2{font-size:17px;color:#1e40af;font-weight:600;padding-bottom:9px;margin-bottom:16px;
  border-bottom:2px solid #dbeafe}
h3{font-size:15px;color:#1e40af;font-weight:600;margin:22px 0 10px}
h3:first-of-type{margin-top:0}
.h3-sub{font-size:12.5px;color:#64748b;font-weight:400}
h4{font-size:13.5px;color:#334155;font-weight:600;margin:18px 0 8px}
h4:first-of-type{margin-top:0}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:6px}
th{background:#2563eb;color:#fff;text-align:left;padding:9px 11px;font-weight:500;
  font-size:12px;white-space:nowrap}
td{padding:9px 11px;border-bottom:1px solid #eef2f6;vertical-align:top}
tbody tr:nth-child(even){background:#f9fafb}
tbody tr:hover{background:#eff6ff}
tr.r-trip td{background:#fff7ed}
tr.r-trip:hover td{background:#ffedd5}
tr.r-food td{background:#f0fdf7}
tr.r-food:hover td{background:#dcfce7}
tr.r-move td{color:#64748b;font-size:12px}
.mono{font-family:Consolas,Monaco,"Courier New",monospace}
.nowrap{white-space:nowrap}
.dim{color:#64748b;font-size:11.5px}
.note-cell{line-height:1.6}
.warn-inline{color:#b45309}
.tag{display:inline-block;font-size:10.5px;padding:1px 7px;border-radius:999px;
  margin-left:5px;white-space:nowrap;font-weight:500}
.tag-g{background:#dcfce7;color:#16a34a}
.tag-o{background:#ffedd5;color:#ea580c}
.tag-y{background:#fef3c7;color:#b45309}
.tag-b{background:#e0e7ff;color:#4338ca}
.note-box{background:#eff6ff;border-left:4px solid #3b82f6;border-radius:6px;
  padding:12px 15px;font-size:12.5px;margin-bottom:16px;line-height:1.7}
.warn-box{background:#fffbeb;border-left:4px solid #f59e0b;border-radius:6px;
  padding:12px 15px;font-size:12.5px;margin-bottom:16px;line-height:1.7}
.kpi{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:4px}
.kpi div{flex:1 1 120px;background:#f8fafc;border:1px solid #e2e8f0;
  border-radius:9px;padding:13px 15px}
.kpi .l{font-size:11.5px;color:#64748b}
.kpi .v{font-size:20px;font-weight:700;color:#1e40af;
  font-family:Consolas,Monaco,monospace;margin-top:2px}
.total{background:linear-gradient(135deg,#1d4ed8,#3b82f6);color:#fff;
  border-radius:10px;padding:16px 20px;margin-bottom:14px}
.total .l{font-size:12.5px;opacity:.92}
.total .v{font-size:30px;font-weight:700;font-family:Consolas,Monaco,monospace;
  line-height:1.2}
code{background:#f3f4f6;color:#1d4ed8;font-family:Consolas,Monaco,monospace;
  font-size:11.5px;padding:1px 5px;border-radius:3px}
ul{margin:6px 0 0 18px;font-size:12.5px;line-height:1.75}
@media print{body{background:#fff}.card{box-shadow:none;border:1px solid #e2e8f0}}
@media(max-width:720px){
  .wrap{padding:12px}.card{padding:16px 14px}
  table{font-size:11.5px}th,td{padding:7px 8px}
  .banner{padding:22px 18px}.banner h1{font-size:21px}
}
</style></head><body>

<div class="banner">
  <h1>${esc(FROM)} → ${esc(TO)}　${DAYS} 天${res.nights ? res.nights + ' 晚' : ''}攻略</h1>
  <div class="sub">${esc(dest ? dest.one_liner : '')}</div>
  <div class="meta">由旅游攻略知识库自动生成 · ${today} ·
    行程由「建议停留时长 + 开放时间 + 景点间距离」排出，非人工编排</div>
</div>

<div class="wrap">

  <div class="card">
    <h2>先看这几条</h2>
    <div class="note-box">
      <b>花费 ${M.yuan(total)} 起</b>是按库里区间下限估的：交通取票价下限×2，
      住宿取「${esc(res.stay ? res.stay.area_name : '中档')}」舒适型下限×${res.nights} 晚${
      peak ? '×旺季系数 ' + (res.stay ? res.stay.peak_multiplier : '1.8') : ''}，
      吃饭按每餐人均估值。<b>全是估值，实际按当日价格浮动。</b>
    </div>
    <div class="warn-box">
      <b>交通时间只算车上</b>，其余取决于你住哪，库里估不准就不写 ——
      出门请自己往前留。<br>
      <b>不存具体车次号</b>，调图会变，出发前用 12306 或高德查当日班次。${
      ss && ss.bad ? `<br><b>季节提醒：</b>${esc(ss.txt)}` : ''}
    </div>
    <div class="total">
      <div class="l">人均预估（不含购物）</div>
      <div class="v">${M.yuan(total)}</div>
    </div>
    <div class="kpi">
      ${spend.train ? `<div><div class="l">往返交通</div><div class="v">${M.yuan(spend.train)}</div></div>` : ''}
      ${spend.hotel ? `<div><div class="l">住宿 ${res.nights} 晚</div><div class="v">${M.yuan(spend.hotel)}</div></div>` : ''}
      <div><div class="l">门票</div><div class="v">${M.yuan(spend.ticket)}</div></div>
      <div><div class="l">吃饭</div><div class="v">${M.yuan(spend.food)}</div></div>
      <div><div class="l">市内交通</div><div class="v">${M.yuan(spend.local)}</div></div>
    </div>
  </div>

  <div class="card">
    <h2>每日行程</h2>
    ${planBlocks()}
    <div class="note-box" style="margin-top:16px;margin-bottom:0">
      日落类机位已尽量卡在日落前（本月约
      <code>${M.hm(M.sunsetMin(dest ? dest.center_lat : 32, M.monthNow()))}</code>，估算值）。
      转场时间按直线距离估，实际用高德更准。想换景点就在手机端「景点」页勾选，
      攻略会按你勾的重排。
    </div>
  </div>

  <div class="card">
    <h2>怎么去　<span class="dim" style="font-weight:400">${routes.length} 种走法</span></h2>
    <table><thead><tr><th style="width:150px">方式</th>
      <th style="width:82px">车上时间</th><th style="width:110px">票价</th>
      <th style="width:170px">站点</th><th>班次 / 提醒</th></tr></thead>
      <tbody>${routeRows()}</tbody></table>
    ${arrivals.length ? `<h3 style="margin-top:24px">到站后怎么去</h3>${arrivalRows()}` : ''}
  </div>

  <div class="card">
    <h2>住哪　<span class="dim" style="font-weight:400">${stays.length} 个片区${
      peak ? ' · 已按旺季房价换算' : ' · 平日价'}</span></h2>
    <div class="note-box">
      住宿最关键的不是订哪家，是<b>住哪个片区</b> —— 住错片区每天多花两小时通勤。
      房价是<b>区间估值</b>，实时房价拿不到，订房去携程或飞猪比价。
    </div>
    <table><thead><tr><th style="width:132px">片区</th><th>为什么住这</th>
      <th style="width:126px">三档房价</th><th style="width:150px">举例</th>
      <th style="width:190px">避坑</th></tr></thead>
      <tbody>${stayRows()}</tbody></table>
  </div>

  <div class="card">
    <h2>吃什么　<span class="dim" style="font-weight:400">${foods.length} 条</span></h2>
    <h3 style="margin-top:0">数据来源</h3>
    ${foodSourceTable()}
    <div class="warn-box" style="margin-top:14px">
      <b>关于评分：本页所有店都没有评分。</b>
      大众点评的评分没有开放接口、抓不到，所以 <code>rating</code> 字段一律留空 ——
      编一个「4.7 分」比不给更糟。<br>
      能合法拿到评分的来源有三个：<b>高德 POI 搜索 API</b>（自带评分与人均，
      有免费额度，也是唯一能自动铺量的途径）、<b>米其林中国官网</b>、
      <b>黑珍珠官网</b>。接上高德之后这一列才会有数。<br>
      「依据高/中/低」是<b>录入时的可信度</b>，不是好吃程度：
      高=官方名录或广为人知；中=知名但细节可能变；低=需重点核实。
    </div>
    <div class="note-box">
      <b>人均全部是估值</b>（<code>price_confidence=low</code>），餐饮价格半年就变，
      出门前请再确认。<b>店铺本身是真的</b> —— 中华老字号可在商务部名录查证，
      地标老店是长期公认的存在。
    </div>
    ${foodBlocks()}
  </div>

  <div class="card">
    <h2>玩什么　<span class="dim" style="font-weight:400">${pois.length} 处</span></h2>
    ${poiBlocks()}
  </div>

  <div class="card">
    <h2>出发前必办</h2>
    <div class="warn-box">
      下面这些<b>错过放票就去不了</b>。库里这批预约规则大多还没对过官方渠道，
      标「未核实」的请自己查一遍官方小程序或公众号。
    </div>
    ${ruleRows()}
  </div>

  <div class="card">
    <h2>这份攻略的边界</h2>
    <ul>
      <li>所有数据<b>未经官方核实</b>（<code>verified=0</code>），门票、房价、人均、
        车次票价都会变，出行前请自己对一遍</li>
      <li>景点坐标是<b>估值</b>（精度约几百米），够用来排分天顺序，不够导航</li>
      <li>餐厅<b>人均是估值</b>，<code>price_confidence</code> 一律标 <code>low</code></li>
      <li>住宿只到<b>片区级</b>，给三档区间 + 旺季系数，不给单店实时房价</li>
      <li>交通<b>只算车上时间</b></li>
      <li>拥挤度、实时房价、实时车次<b>都拿不到</b>，产品设计上正面承认</li>
    </ul>
  </div>

</div></body></html>`;

const outDir = path.join(ROOT, 'exports');
fs.mkdirSync(outDir, { recursive: true });
const file = path.join(outDir, `${FROM}-${TO}-攻略.html`);
fs.writeFileSync(file, html, 'utf8');

console.log(`已生成 ${path.relative(ROOT, file)}  (${(html.length / 1024).toFixed(1)} KB)`);
console.log(`  ${DAYS} 天${res.nights} 晚 · 人均预估 ${M.yuan(total)}`);
console.log(`  行程 ${res.plan.length} 天 / 共 ${
  res.plan.reduce((n, d) => n + d.items.length, 0)} 项`);
console.log(`  交通 ${routes.length} 种 · 住宿 ${stays.length} 片区 · 美食 ${
  foods.length} 条 · 景点 ${pois.length} 处 · 到站接驳 ${arrivals.length} 条`);
if (rules.length) console.log(`  需预约 ${rules.length} 项`);
