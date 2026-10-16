/* 长期走势 · 回撤 · 牛熊周期  ——  前端渲染脚本（原生 JS + ECharts） */
(function () {
  'use strict';

  var D = window.__DATA__;
  if (!D || typeof echarts === 'undefined') return;

  /* ------------------------------------------------------------ 常量 */
  var C = {
    nav: '#2b7fd4',
    navFill: ['rgba(43,127,212,0.22)', 'rgba(43,127,212,0.01)'],
    dd: '#3fae6a',
    ddFill: ['rgba(63,174,106,0.34)', 'rgba(63,174,106,0.03)'],
    bearBand: 'rgba(134,194,164,0.62)',
    bearBandPending: 'rgba(134,194,164,0.26)',
    grid: '#eef2f6',
    axis: '#9fb0c0',
    axisLine: '#dbe3ea',
    text: '#1b2430',
    sub: '#6b7a8d'
  };

  var charts = [];
  function regChart(dom) {
    var c = echarts.init(dom, null, { renderer: 'canvas' });
    charts.push(c);
    return c;
  }
  var rt = null;
  window.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(function () { charts.forEach(function (c) { c.resize(); }); }, 120);
  });

  var $ = function (id) { return document.getElementById(id); };
  var isMobile = function () { return window.innerWidth < 720; };

  /* ------------------------------------------------------------ 格式化 */
  function pctStr(v, d) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    d = d === undefined ? 2 : d;
    return (v > 0 ? '+' : '') + v.toFixed(d) + '%';
  }
  function dirClass(v) {
    if (v === null || v === undefined || isNaN(v)) return 'flat';
    return v > 0 ? 'up' : (v < 0 ? 'down' : 'flat');
  }
  function xStr(v, d) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return v.toFixed(d === undefined ? 2 : d) + 'x';
  }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (m) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m];
    });
  }
  function lastIndexLE(arr, target) {
    var lo = 0, hi = arr.length - 1, ans = -1;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      if (arr[mid] <= target) { ans = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    return ans;
  }
  function fmtMultiple(v) {
    if (v >= 10) return v.toFixed(0) + 'x';
    if (v >= 1) return v.toFixed(1) + 'x';
    if (v >= 0.1) return v.toFixed(2) + 'x';
    return v.toFixed(3) + 'x';
  }
  /* 对数刻度：把净值取 log10 后交给线性轴呈现，刻度落在 log 空间的整数格上
     （1.0x / 1.3x / 1.6x / 2.0x / 2.5x …）。相比 ECharts 原生 log 轴
     自动生成的三两个刻度，这样更密、更贴近参考图的观感。 */
  function logScale(values) {
    var lv = values.map(function (v) { return Math.log10(v); });
    var lmin = Math.min.apply(null, lv);
    var lmax = Math.max.apply(null, lv);
    var span = lmax - lmin;
    var step = span > 1.2 ? 0.4
      : span > 0.6 ? 0.2
      : span > 0.3 ? 0.1
      : span > 0.14 ? 0.05
      : 0.02;
    return {
      min: Math.floor(lmin / step) * step,
      max: Math.ceil(lmax / step) * step,
      step: step
    };
  }
  function linAxis(scale) {
    return {
      type: 'value',
      min: scale.min,
      max: scale.max,
      interval: scale.step,
      splitLine: { lineStyle: { color: C.grid } },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: C.axis,
        fontSize: 11.5,
        formatter: function (v) { return fmtMultiple(Math.pow(10, v)); }
      }
    };
  }
  function timeAxis() {
    return {
      type: 'time',
      boundaryGap: false,
      axisLine: { lineStyle: { color: C.axisLine } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: {
        color: C.axis,
        fontSize: 11.5,
        hideOverlap: true,
        formatter: { year: '{yyyy}', month: "{yyyy}-{MM}" }
      }
    };
  }
  function baseGrid(extra) {
    var g = {
      left: isMobile() ? 44 : 58,
      right: isMobile() ? 46 : 74,
      top: 26,
      bottom: 30
    };
    if (extra) { for (var k in extra) { g[k] = extra[k]; } }
    return g;
  }
  function tooltipBase(fmt) {
    return {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.97)',
      borderColor: '#e2e8ef',
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: C.text, fontSize: 12 },
      extraCssText: 'box-shadow:0 6px 20px -8px rgba(23,43,77,.25);border-radius:9px;',
      axisPointer: { type: 'line', lineStyle: { color: '#c8d6e3', type: 'dashed' } },
      formatter: fmt
    };
  }

  /* ------------------------------------------------------------ 概览条 */
  function renderOverview() {
    var c = D.cagr, dd = D.drawdown;
    var items = [
      { k: '期末净值倍数', v: xStr(c.total_multiple), cls: 'nav' },
      { k: '长期年化收益 (CAGR)', v: pctStr(c.cagr_pct), cls: dirClass(c.cagr_pct) },
      { k: '区间累计收益', v: pctStr(c.total_return_pct), cls: dirClass(c.total_return_pct) },
      { k: '历史最大回撤', v: dd.max_drawdown_pct.toFixed(2) + '%', cls: 'down' },
      { k: '当前距历史前高', v: pctStr(dd.current_drawdown_pct), cls: dirClass(dd.current_drawdown_pct) },
      { k: '统计区间', v: c.years.toFixed(1) + ' 年', cls: '' }
    ];
    $('overview').innerHTML = items.map(function (it) {
      return '<div class="ov-item"><div class="ov-k">' + esc(it.k) + '</div>' +
        '<div class="ov-v ' + it.cls + '">' + esc(it.v) + '</div></div>';
    }).join('');
  }

  /* ------------------------------------------------------------ ① 对数净值 */
  function renderNav() {
    var ch = regChart($('chart-nav'));
    var scale = logScale(D.nav);
    var data = D.dates.map(function (d, i) { return [d, Math.log10(D.nav[i])]; });
    var cagr = D.cagr.cagr_pct;

    ch.setOption({
      animationDuration: 600,
      grid: baseGrid({ top: 30, bottom: 28 }),
      tooltip: tooltipBase(function (ps) {
        var p = ps[0];
        return '<b>' + p.axisValueLabel + '</b><br/>净值倍数　<b>' +
          Math.pow(10, p.value[1]).toFixed(4) + 'x</b>';
      }),
      graphic: [{
        type: 'text',
        right: isMobile() ? baseGrid().right + 4 : baseGrid().right + 16,
        top: 40,
        silent: true,
        style: {
          text: 'CAGR ' + (cagr > 0 ? '+' : '') + cagr.toFixed(1) + '%',
          fill: '#cfd9e3',
          fontSize: isMobile() ? 14 : 21,
          fontWeight: 700
        }
      }],
      xAxis: timeAxis(),
      yAxis: linAxis(scale),
      series: [{
        name: '净值倍数',
        type: 'line',
        data: data,
        showSymbol: false,
        symbolSize: 4,
        sampling: 'lttb',
        lineStyle: { width: 1.6, color: C.nav },
        itemStyle: { color: C.nav },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: C.navFill[0] },
            { offset: 1, color: C.navFill[1] }
          ])
        },
        markPoint: {
          symbol: 'circle',
          symbolSize: 7,
          itemStyle: { color: C.nav, borderColor: '#fff', borderWidth: 1.5 },
          label: {
            show: true,
            position: 'right',
            distance: 7,
            color: C.text,
            fontSize: 13,
            fontWeight: 700,
            formatter: function () { return xStr(D.cagr.total_multiple); }
          },
          data: [{ coord: [D.dates[D.dates.length - 1], Math.log10(D.nav[D.nav.length - 1])] }]
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#dfe7ee', type: 'dashed', width: 1 },
          label: { show: false },
          data: [{ yAxis: 0 }]
        }
      }]
    });
    ch.resize();

    var m = [
      { k: '起始日期', v: D.cagr.start_date, cls: 'dim' },
      { k: '起始净值', v: '1.00x', cls: 'nav' },
      { k: '期末净值', v: xStr(D.cagr.total_multiple), cls: 'nav' },
      { k: '区间累计收益', v: pctStr(D.cagr.total_return_pct), cls: dirClass(D.cagr.total_return_pct) },
      { k: '长期年化 (CAGR)', v: pctStr(D.cagr.cagr_pct), cls: dirClass(D.cagr.cagr_pct) },
      { k: '统计跨度', v: '约 ' + D.cagr.years.toFixed(1) + ' 年', cls: 'dim' }
    ];
    $('nav-metrics').innerHTML = m.map(function (it) {
      return '<div class="m"><div class="mk">' + esc(it.k) + '</div>' +
        '<div class="mv ' + it.cls + '">' + esc(it.v) + '</div></div>';
    }).join('');
  }

  /* ------------------------------------------------------------ ② 回撤 */
  function renderDrawdown() {
    var ch = regChart($('chart-dd'));
    var dd = D.drawdown;
    var data = D.dates.map(function (d, i) { return [d, dd.series[i]]; });
    var span = Math.abs(dd.max_drawdown_pct);
    var iv = span > 45 ? 10 : (span > 22 ? 5 : 2);
    var lo = Math.floor(dd.max_drawdown_pct / iv) * iv;

    ch.setOption({
      animationDuration: 600,
      grid: baseGrid({ top: 24, bottom: 28, right: isMobile() ? 62 : 88 }),
      tooltip: tooltipBase(function (ps) {
        var p = ps[0];
        return '<b>' + p.axisValueLabel + '</b><br/>距前高　<b style="color:' + C.dd + '">' +
          p.value[1].toFixed(2) + '%</b>';
      }),
      title: {
        text: '当前距历史前高\n' + dd.current_drawdown_pct.toFixed(2) + '%',
        top: 30,
        right: isMobile() ? 10 : 18,
        textAlign: 'right',
        textStyle: { color: '#2f6d4b', fontSize: 12, fontWeight: 600, lineHeight: 16 },
        backgroundColor: 'rgba(255,255,255,.92)',
        borderColor: '#cfe6d8',
        borderWidth: 1,
        borderRadius: 5,
        padding: [3, 7]
      },
      xAxis: timeAxis(),
      yAxis: {
        type: 'value',
        min: lo,
        max: 0,
        interval: iv,
        splitLine: { lineStyle: { color: C.grid } },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: C.axis, fontSize: 11.5, formatter: '{value}%' }
      },
      series: [{
        name: '回撤',
        type: 'line',
        data: data,
        showSymbol: false,
        sampling: 'lttb',
        lineStyle: { width: 1.4, color: C.dd },
        itemStyle: { color: C.dd },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: C.ddFill[0] },
            { offset: 1, color: C.ddFill[1] }
          ])
        },
        markLine: {
          silent: true,
          symbol: ['none', 'none'],
          lineStyle: { color: '#c2cfdb', type: 'dashed', width: 1 },
          label: {
            show: true,
            position: 'middle',
            formatter: dd.decline_months.toFixed(0) + 'm',
            color: C.sub,
            fontSize: 11,
            backgroundColor: 'rgba(255,255,255,.9)',
            padding: [2, 4]
          },
          data: [[
            { coord: [dd.peak_date, 0] },
            { coord: [dd.trough_date, dd.max_drawdown_pct] }
          ]]
        },
        markPoint: {
          symbol: 'circle',
          symbolSize: 6,
          itemStyle: { color: C.dd, borderColor: '#fff', borderWidth: 1.5 },
          data: [
            {
              coord: [dd.trough_date, dd.max_drawdown_pct],
              label: {
                show: true,
                position: 'bottom',
                distance: 8,
                color: '#2f6d4b',
                fontSize: 12,
                fontWeight: 600,
                backgroundColor: 'rgba(255,255,255,.94)',
                borderColor: '#cfe6d8',
                borderWidth: 1,
                borderRadius: 5,
                padding: [3, 7],
                formatter: '最大回撤 ' + dd.max_drawdown_pct.toFixed(2) + '%'
              }
            },
            {
              coord: [D.dates[D.dates.length - 1], dd.current_drawdown_pct],
              symbol: 'emptyCircle',
              symbolSize: 8,
              itemStyle: { color: '#fff', borderColor: C.dd, borderWidth: 2 },
              label: { show: false }
            }
          ]
        }
      }]
    });
    ch.resize();

    var m = [
      { k: '最大回撤幅度', v: dd.max_drawdown_pct.toFixed(2) + '%', cls: 'down' },
      { k: '峰值日期', v: dd.peak_date + '（' + xStr(dd.peak_nav) + '）', cls: 'dim' },
      { k: '谷底日期', v: dd.trough_date + '（' + xStr(dd.trough_nav) + '）', cls: 'dim' },
      { k: '下跌历时', v: dd.decline_months.toFixed(1) + ' 个月', cls: 'down' },
      {
        k: '修复情况',
        v: dd.recovered ? '已于 ' + dd.recover_date + ' 修复' : '至今尚未修复',
        cls: dd.recovered ? 'dim' : 'down'
      },
      {
        k: '回撤持续',
        v: dd.duration_months.toFixed(1) + ' 个月' + (dd.recovered ? '' : '（进行中）'),
        cls: 'dim'
      },
      { k: '当前距历史前高', v: pctStr(dd.current_drawdown_pct), cls: dirClass(dd.current_drawdown_pct) }
    ];
    $('dd-metrics').innerHTML = m.map(function (it) {
      return '<div class="m"><div class="mk">' + esc(it.k) + '</div>' +
        '<div class="mv ' + it.cls + '">' + esc(it.v) + '</div></div>';
    }).join('');
  }

  /* ------------------------------------------------------------ ③ 牛熊 */
  var swing = { freq: 'month', th: 20 };

  function currentSwing() {
    var key = swing.freq + '_' + swing.th;
    return D.swings[key] || D.swings[Object.keys(D.swings)[0]];
  }

  function renderSwing() {
    var sw = currentSwing();
    var s = sw.stats;
    var useMonth = sw.freq === 'month';
    var dates = useMonth ? D.m_dates : D.dates;
    var navs = useMonth ? D.m_nav : D.nav;

    /* --- 统计卡片 --- */
    $('swing-stats').innerHTML = [
      { k: '牛市段数', v: s.bull_count, u: '段 / ' + s.bull_months + ' 个月', cls: 'bull' },
      { k: '熊市段数', v: s.bear_count, u: '段 / ' + s.bear_months + ' 个月', cls: 'bear' },
      { k: '牛市单段平均', v: s.bull_avg_months, u: '个月', cls: '' },
      { k: '熊市单段平均', v: s.bear_avg_months, u: '个月', cls: '' },
      { k: '熊市时长占比', v: s.bear_share_pct, u: '%', cls: 'bear' },
      { k: '牛市创出新高', v: s.bull_new_high_count, u: '/ ' + s.bull_count + ' 段', cls: 'bull' }
    ].map(function (it) {
      return '<div class="st-item"><div class="st-k">' + esc(it.k) + '</div>' +
        '<div class="st-v ' + it.cls + '">' + esc(it.v) + '<small>' + esc(it.u) + '</small></div></div>';
    }).join('');

    /* --- 主图 --- */
    var scale = logScale(navs);
    var data = dates.map(function (d, i) { return [d, Math.log10(navs[i])]; });
    var indexOf = {};
    dates.forEach(function (d, i) { indexOf[d] = i; });

    var bears = sw.phases.filter(function (p) { return p.type === 'bear'; });
    var highs = sw.phases.filter(function (p) { return p.type === 'bull' && p.new_high; })
      .map(function (p) { return [p.end, navs[indexOf[p.end]]]; })
      .filter(function (d) { return d[1] !== undefined; })
      .map(function (d) { return [d[0], Math.log10(d[1])]; });

    var series = [{
      name: '净值倍数',
      type: 'line',
      data: data,
      showSymbol: false,
      sampling: 'lttb',
      lineStyle: { width: 1.6, color: '#1f4e79' },
      itemStyle: { color: '#1f4e79' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(31,78,121,0.12)' },
          { offset: 1, color: 'rgba(31,78,121,0.0)' }
        ])
      },
      markArea: {
        silent: true,
        data: bears.map(function (p) {
          return [
            { xAxis: p.start, itemStyle: { color: p.confirmed ? C.bearBand : C.bearBandPending } },
            { xAxis: p.end }
          ];
        })
      }
    }];

    if (highs.length) {
      series.push({
        name: '牛市创出历史新高',
        type: 'scatter',
        symbol: 'triangle',
        symbolSize: 10,
        z: 12,
        itemStyle: { color: '#12293f' },
        data: highs
      });
    }

    var ch = chartSwing || (chartSwing = regChart($('chart-swing')));
    ch.setOption({
      animationDuration: 500,
      grid: baseGrid({ top: 38, bottom: 26 }),
      tooltip: tooltipBase(function (ps) {
        var p = ps[0];
        var out = '<b>' + p.axisValueLabel + '</b><br/>净值倍数　<b>' +
          Math.pow(10, p.value[1]).toFixed(3) + 'x</b>';
        var hit = sw.phases.filter(function (x) { return x.start <= p.value[0] && p.value[0] <= x.end; })[0];
        if (hit) {
          out += '<br/><span style="color:#6b7a8d">' +
            (hit.type === 'bull' ? '牛市段' : '熊市段') +
            '　' + hit.start + ' ~ ' + hit.end + '　' +
            (hit.change_pct > 0 ? '+' : '') + hit.change_pct + '%' +
            (hit.confirmed ? '' : '（未确认）') + '</span>';
        }
        return out;
      }),
      legend: {
        show: true,
        top: 0,
        right: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: C.sub, fontSize: 11.5 },
        data: highs.length ? ['净值倍数', '牛市创出历史新高'] : ['净值倍数']
      },
      xAxis: timeAxis(),
      yAxis: linAxis(scale),
      series: series
    }, true);
    ch.resize();

    /* --- 阶段时长色带 --- */
    $('phase-band').innerHTML = sw.phases.map(function (p) {
      var tip = p.start + ' ~ ' + p.end + ' · ' + (p.type === 'bull' ? '牛市' : '熊市') +
        ' · ' + (p.change_pct > 0 ? '+' : '') + p.change_pct + '% · ' + p.months + ' 个月' +
        (p.confirmed ? '' : '（尚未确认）');
      return '<div class="ph ' + p.type + (p.confirmed ? '' : ' pending') + '"' +
        ' style="flex:' + Math.max(p.months, 1) + ' 0 0" title="' + esc(tip) + '">' +
        '<span>' + (p.type === 'bull' ? '牛' : '熊') + p.months + '</span></div>';
    }).join('');

    $('swing-legend').innerHTML = [
      '<span><i style="background:#e8918d"></i>牛市区间</span>',
      '<span><i style="background:#86c2a4"></i>熊市区间</span>',
      '<span><i style="background:rgba(134,194,164,.42)"></i>尚未被反向摆动确认</span>',
      '<span><i style="background:#12293f;border-radius:2px"></i>该轮牛市创出历史新高</span>',
      '<span style="color:#9aa7b5">当前口径：' +
      (sw.freq === 'month' ? '月线' : '日线') + ' · ±' + sw.threshold + '%</span>'
    ].join('');
  }

  var chartSwing = null;

  /* ------------------------------------------------------------ ④ 多尺度 */
  function renderPeriods() {
    var firstDate = D.dates[0];
    $('period-grid').innerHTML = D.periods.map(function (p) {
      var cls = p.available ? dirClass(p.pct) : 'flat';
      var val = p.available ? pctStr(p.pct) : '—';
      var label = p.label;
      // 自成立以来卡片：基准为上市首日后显示「自成立以来」，自定义日期时显示「自X日以来」
      if (p.key === 'since') {
        label = (p.base_date && p.base_date === firstDate)
          ? '自成立以来'
          : ('自' + (p.base_date || '') + '以来');
      }
      return '<div class="pcard ' + cls + '">' +
        '<div class="pl">' + esc(label) + '</div>' +
        '<div class="pv">' + esc(val) + '</div>' +
        '<div class="pn">' + esc(p.note || '') + '</div></div>';
    }).join('');
  }

  function bindSince() {
    var input = $('since-date');
    if (!input) return;
    input.addEventListener('change', function () {
      var v = input.value;
      var card = D.periods.filter(function (p) { return p.key === 'since'; })[0];
      if (!card) return;
      var idx = lastIndexLE(D.dates, v);
      if (!v || idx < 0) {
        card.available = false;
        card.pct = null;
        card.note = '日期超出区间';
      } else {
        var base = D.nav[idx];
        var pct = (D.nav[D.nav.length - 1] / base - 1) * 100;
        pct = Math.round(pct * 100) / 100;
        card.available = true;
        card.pct = pct;
        card.note = '基准 ' + D.dates[idx];
        card.direction = dirClass(pct);
      }
      renderPeriods();
    });
  }

  /* ------------------------------------------------------------ 交互绑定 */
  function bindSeg(id, onChange) {
    var box = $(id);
    if (!box) return;
    box.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('button') : null;
      if (!btn) return;
      Array.prototype.forEach.call(box.querySelectorAll('button'), function (b) {
        b.classList.toggle('active', b === btn);
      });
      box.dataset.value = btn.dataset.v;
      onChange(btn.dataset.v);
    });
  }

  function bindRefresh() {
    var btn = $('btn-refresh');
    if (!btn) return;
    btn.addEventListener('click', function () {
      btn.disabled = true;
      var old = btn.textContent;
      btn.textContent = '刷新中…';
      fetch('/api/refresh?code=' + encodeURIComponent(D.meta.code), { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.ok) { location.reload(); }
          else { alert('刷新失败：' + j.error); btn.disabled = false; btn.textContent = old; }
        })
        .catch(function (e) {
          alert('刷新失败：' + e.message);
          btn.disabled = false;
          btn.textContent = old;
        });
    });
  }

  /* ------------------------------------------------------------ 启动 */
  renderOverview();
  renderNav();
  renderDrawdown();
  renderSwing();
  renderPeriods();
  bindSince();
  bindRefresh();
  bindSeg('seg-freq', function (v) { swing.freq = v; renderSwing(); });
  bindSeg('seg-th', function (v) { swing.th = parseInt(v, 10); renderSwing(); });
})();
