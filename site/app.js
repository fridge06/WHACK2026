// Launch Day Alpha front end (PLAN.md section 6).
// Reads data/games.json (written by the pipeline) and draws one game at a time.
(function () {
  "use strict";

  const DAY = 86400000;
  const KEY_LAST_SET = "lda-last-set";
  const KEY_THEME = "lda-theme";
  const MINUS = "−";
  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Browser storage is a convenience only; the page must work without it.
  const store = {
    get(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { window.localStorage.setItem(key, value); } catch (e) { /* unavailable */ } },
  };

  /* ------------------------------------------------------------------
     Formatting
  ------------------------------------------------------------------- */
  const nf = (min, max) => new Intl.NumberFormat("en-GB", { minimumFractionDigits: min, maximumFractionDigits: max });
  const nf0 = nf(0, 0), nf1 = nf(1, 1);

  function utc(s) {
    const [y, m, d] = s.split("-").map(Number);
    return Date.UTC(y, m - 1, d || 1);
  }
  function fmtDate(ms) {
    return new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  }
  function fmtMonthYear(ms) {
    return new Date(ms).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
  }
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function shortMonth(ms) {
    return MONTHS[new Date(ms).getUTCMonth()];
  }
  // Signed percentage: "+12.4%", "−8.0%", "0%".
  function pct(v, f) {
    const fmt = f || nf1;
    if (Math.abs(v) < 0.05 && fmt === nf1) return "0%";
    return (v > 0 ? "+" : v < 0 ? MINUS : "") + fmt.format(Math.abs(v)) + "%";
  }
  function dayLabel(d) {
    if (d === 0) return "launch day";
    return (d > 0 ? "day +" : "day " + MINUS) + Math.abs(d);
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function niceTicks(min, max, count) {
    const span = (max - min) || Math.abs(max) || 1;
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const start = Math.floor(min / step) * step;
    const end = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = start; v <= end + step * 1e-9; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }
  // Right-axis labels in % change, decimals from the tick step.
  function axisPct(ticks) {
    const step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
    const dec = Math.min(2, Math.max(0, Math.ceil(-Math.log10(step) - 1e-9)));
    const f = nf(dec, dec);
    return (v) => (Math.abs(v) < 1e-9 ? "0%" : pct(v, f));
  }

  /* ------------------------------------------------------------------
     Data and selection
  ------------------------------------------------------------------- */
  function shuffle(list) {
    const a = list.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }
  const setKey = (games) => games.map((g) => g.id).sort().join(",");

  function pickGames(all, n) {
    // ?games=id1,id2 lets a presenter choose the games (in that order).
    const requested = (new URLSearchParams(window.location.search).get("games") || "")
      .split(",").map((s) => s.trim()).filter(Boolean);
    if (requested.length) {
      const byId = new Map(all.map((g) => [g.id, g]));
      const chosen = [...new Set(requested)].map((id) => byId.get(id)).filter(Boolean);
      if (chosen.length) return chosen;
    }
    let pick = shuffle(all).slice(0, n);
    // Best effort: avoid showing exactly the same set as last visit.
    if (all.length > n && setKey(pick) === store.get(KEY_LAST_SET)) pick = shuffle(all).slice(0, n);
    store.set(KEY_LAST_SET, setKey(pick));
    return pick;
  }

  function prepare(g) {
    g._ms = g.market.map((p) => utc(p.date));
    g._launch = utc(g.launch);
    g._popMs = g.popularity.map((p) => utc(p.mid));
    return g;
  }

  /* ------------------------------------------------------------------
     Text
  ------------------------------------------------------------------- */
  let META = null;

  // "In its first month, CD Projekt's value fell 23.6% behind its market:
  //  down 30.1%, while its market fell 6.5%."
  function verdictHtml(g) {
    const v = g.verdict;
    const pub = escapeHtml(g.publisher);
    const gap = `<strong>${nf1.format(Math.abs(v.gap_pct))}%</strong>`;
    const lead = v.gap_pct < 0
      ? `${escapeHtml(META.verdict_phrase)}, ${pub}’s value fell ${gap} behind its market`
      : `${escapeHtml(META.verdict_phrase)}, ${pub}’s value pulled ${gap} ahead of its market`;
    const move = (x, up, down) => (Math.abs(x) < 0.05 ? "was flat" : `${x > 0 ? up : down} ${nf1.format(Math.abs(x))}%`);
    return `${lead}: ${move(v.pct, "up", "down")}, while its market ${move(v.implied_pct, "rose", "fell")}.`;
  }

  function metaLine(g) {
    let s = `Published by ${g.publisher}.`;
    if (g.ticker) s += ` Listed ${g.city ? "in " + g.city + " " : ""}as ${g.ticker}.`;
    s += ` Launched ${fmtDate(g._launch)}.`;
    return s;
  }

  function updateText(g, animate) {
    $("title").textContent = g.name;
    $("meta").textContent = metaLine(g);
    $("verdict").innerHTML = verdictHtml(g);
    const labels = new Map(META.signals.map((s) => [s.id, s.label]));
    $("sources").textContent = "Popularity for this game combines: " + g.signals_used.map((id) => labels.get(id) || id).join(", ") + ".";
    if (animate && !reduceMotion) {
      const el = $("copy");
      el.classList.remove("swap");
      void el.offsetWidth;
      el.classList.add("swap");
    }
  }

  /* ------------------------------------------------------------------
     Chart
  ------------------------------------------------------------------- */
  let chartState = null;

  function popSegments(g) {
    const segs = [];
    let cur = [];
    g.popularity.forEach((p, i) => {
      if (p.value == null) { if (cur.length) segs.push(cur); cur = []; }
      else cur.push(i);
    });
    if (cur.length) segs.push(cur);
    return segs;
  }

  function monthTicks(xMin, xMax) {
    const d = new Date(xMin);
    let y = d.getUTCFullYear(), mo = d.getUTCMonth();
    if (Date.UTC(y, mo, 1) < xMin) mo += 1;
    const ticks = [];
    for (let ms = Date.UTC(y, mo, 1); ms <= xMax; ms = Date.UTC(y, ++mo, 1)) ticks.push(ms);
    return ticks;
  }

  function render(g, animate) {
    const box = $("chart");
    const svg = $("svg");
    const W = Math.max(300, box.clientWidth);
    const narrow = W < 560;
    const H = Math.round(Math.max(280, Math.min(460, W * 0.5)));
    // Narrow screens stack the two axis titles, so the plot starts lower.
    const m = { l: narrow ? 34 : 44, r: narrow ? 52 : 60, t: narrow ? 66 : 50, b: 30 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const f1 = (n) => n.toFixed(1);

    // Time axis covers the market window and every monthly point (PLAN.md 6).
    const xMin = Math.min(g._ms[0], g._popMs[0]);
    const xMax = Math.max(g._ms[g._ms.length - 1], g._popMs[g._popMs.length - 1]);
    const x = (ms) => m.l + (ms - xMin) / (xMax - xMin) * iw;

    const popVals = g.popularity.filter((p) => p.value != null).map((p) => p.value);
    const pTicks = niceTicks(0, Math.max(100, ...popVals) * 1.04, 4);
    const pTop = pTicks[pTicks.length - 1];
    const yL = (v) => m.t + ih - (v / pTop) * ih;

    // Right axis: % change since launch, always including 0%.
    const vals = g.market.flatMap((p) => [p.pct, p.implied_pct]).concat([0]);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.12 || 1;
    const vTicks = niceTicks(lo - pad, hi + pad, 4);
    const vLo = vTicks[0], vHi = vTicks[vTicks.length - 1];
    const yR = (v) => m.t + ih - ((v - vLo) / (vHi - vLo)) * ih;
    const vFmt = axisPct(vTicks);

    const linePath = (idx, fx, fy) => idx.map((i, k) => (k ? "L" : "M") + f1(fx(i)) + "," + f1(fy(i))).join("");
    const all = g.market.map((_, i) => i);
    const mvLine = linePath(all, (i) => x(g._ms[i]), (i) => yR(g.market[i].pct));
    const benchLine = linePath(all, (i) => x(g._ms[i]), (i) => yR(g.market[i].implied_pct));
    const post = all.filter((i) => g.market[i].d >= 0);
    const gapArea = linePath(post, (i) => x(g._ms[i]), (i) => yR(g.market[i].pct)) +
      post.slice().reverse().map((i) => "L" + f1(x(g._ms[i])) + "," + f1(yR(g.market[i].implied_pct))).join("") + "Z";

    let s = "";
    vTicks.forEach((v) => {
      const cls = Math.abs(v) < 1e-9 ? "grid zero" : "grid";
      s += `<line class="${cls}" x1="${m.l}" x2="${m.l + iw}" y1="${f1(yR(v))}" y2="${f1(yR(v))}" />`;
      s += `<text x="${m.l + iw + 8}" y="${f1(yR(v) + 4)}">${vFmt(v)}</text>`;
    });
    pTicks.forEach((v) => {
      s += `<text x="${m.l - 8}" y="${f1(yL(v) + 4)}" text-anchor="end">${nf0.format(v)}</text>`;
    });
    s += `<line class="baseline" x1="${m.l}" x2="${m.l + iw}" y1="${m.t + ih}" y2="${m.t + ih}" />`;

    // Month ticks at the start of each month; thin out labels if space is tight.
    const ticks = monthTicks(xMin, xMax);
    const every = iw / Math.max(1, ticks.length) >= 46 ? 1 : iw / Math.max(1, ticks.length) >= 26 ? 2 : 3;
    let lastYear = null;
    ticks.forEach((ms, k) => {
      const tx = f1(x(ms));
      s += `<line class="tick" x1="${tx}" x2="${tx}" y1="${m.t + ih}" y2="${m.t + ih + 5}" />`;
      if (k % every) return;
      const year = new Date(ms).getUTCFullYear();
      const label = shortMonth(ms) + (year !== lastYear ? " " + year : "");
      lastYear = year;
      s += `<text x="${tx}" y="${m.t + ih + 20}" text-anchor="middle">${label}</text>`;
    });

    s += `<text class="axis-title-pop" x="0" y="14">${escapeHtml(META.popularity_label)}</text>`;
    s += `<text class="axis-title-mv" x="${W}" y="${narrow ? 32 : 14}" text-anchor="end">Market value, change since launch</text>`;

    // Popularity: line and light area per run of known months; gaps stay gaps.
    const segs = popSegments(g);
    const base = f1(yL(0));
    segs.forEach((seg) => {
      if (seg.length < 2) return;
      const line = linePath(seg, (i) => x(g._popMs[i]), (i) => yL(g.popularity[i].value));
      const area = line + `L${f1(x(g._popMs[seg[seg.length - 1]]))},${base}L${f1(x(g._popMs[seg[0]]))},${base}Z`;
      s += `<path class="pop-area fade" d="${area}" />`;
    });
    s += `<path class="gap-area fade" d="${gapArea}" />`;
    s += `<path class="bench-line fade" d="${benchLine}" />`;
    segs.forEach((seg) => {
      if (seg.length < 2) return;
      s += `<path class="pop-line draw" d="${linePath(seg, (i) => x(g._popMs[i]), (i) => yL(g.popularity[i].value))}" />`;
    });
    s += `<path class="mv-line draw" d="${mvLine}" />`;
    g.popularity.forEach((p, i) => {
      if (p.value == null) return;
      s += `<circle class="pop-dot fade" cx="${f1(x(g._popMs[i]))}" cy="${f1(yL(p.value))}" r="3.5" />`;
    });

    const lx = f1(x(g._launch));
    s += `<line class="launch-line" x1="${lx}" x2="${lx}" y1="${m.t - 4}" y2="${m.t + ih}" />`;
    s += `<text class="launch-label" x="${lx}" y="${m.t - 10}" text-anchor="middle">Launch</text>`;

    s += `<g id="hover" style="display:none">
            <line id="hoverLine" class="hover-line" y1="${m.t}" y2="${m.t + ih}" />
            <circle id="hoverPop" class="hover-pop" r="5" />
            <circle id="hoverMv" class="hover-mv" r="5" />
          </g>`;
    s += `<rect id="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent" />`;

    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", W);
    svg.setAttribute("height", H);
    const desc = `${g.name}: monthly popularity and ${g.publisher}’s daily market value from ${fmtDate(g._ms[0])} to ${fmtDate(g._ms[g._ms.length - 1])}.`;
    svg.innerHTML = `<desc id="svgDesc">${escapeHtml(desc)}</desc>` + s;

    chartState = { g, m, iw, x, yL, yR, xMin, xMax };

    if (animate && !reduceMotion) {
      svg.querySelectorAll(".draw").forEach((el, i) => {
        const len = el.getTotalLength();
        el.style.strokeDasharray = len;
        el.style.strokeDashoffset = len;
        el.getBoundingClientRect();
        el.style.transition = `stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1) ${i * 0.12}s`;
        el.style.strokeDashoffset = 0;
      });
      svg.querySelectorAll(".fade").forEach((el) => {
        el.style.opacity = 0;
        el.getBoundingClientRect();
        el.style.transition = "opacity 0.6s ease 0.8s";
        el.style.opacity = 1;
      });
    }

    const hit = $("hit");
    hit.addEventListener("pointermove", onHover);
    hit.addEventListener("pointerdown", onHover);
    hit.addEventListener("pointerleave", hideHover);
  }

  function onHover(e) {
    if (!chartState) return;
    const { g, m, iw, x, yL, yR, xMin, xMax } = chartState;
    const svg = $("svg");
    const rect = svg.getBoundingClientRect();
    const scale = rect.width / svg.viewBox.baseVal.width;
    const ms = xMin + ((e.clientX - rect.left) / scale - m.l) / iw * (xMax - xMin);
    const i = Math.max(0, Math.min(g.market.length - 1, Math.round((ms - g._ms[0]) / DAY)));
    const p = g.market[i];
    const k = g.popularity.findIndex((q) => q.month === p.date.slice(0, 7));
    const pop = k >= 0 ? g.popularity[k] : null;

    $("hover").style.display = "";
    const hx = x(g._ms[i]);
    $("hoverLine").setAttribute("x1", hx);
    $("hoverLine").setAttribute("x2", hx);
    $("hoverMv").setAttribute("cx", hx);
    $("hoverMv").setAttribute("cy", yR(p.pct));
    const hp = $("hoverPop");
    if (pop && pop.value != null) {
      hp.style.display = "";
      hp.setAttribute("cx", x(g._popMs[k]));
      hp.setAttribute("cy", yL(pop.value));
    } else {
      hp.style.display = "none";
    }

    const tip = $("tooltip");
    const popText = pop && pop.value != null ? nf1.format(pop.value) : "no data";
    tip.innerHTML =
      `<b>${fmtDate(g._ms[i])}</b>, ${dayLabel(p.d)}<br>` +
      `Market value: ${pct(p.pct)} since launch<br>` +
      `If it had moved with its market: ${pct(p.implied_pct)}<br>` +
      (p.trading ? "" : `<span class="dim">Market closed: last close shown</span><br>`) +
      `Popularity (${fmtMonthYear(utc(p.date.slice(0, 7)))}): ${popText}`;
    tip.style.opacity = 1;
    const boxW = $("chart").clientWidth;
    const tipW = tip.offsetWidth;
    let left = hx * scale + 14;
    if (left + tipW > boxW) left = hx * scale - tipW - 14;
    tip.style.transform = `translate(${Math.max(0, left)}px, ${m.t * scale}px)`;
  }

  function hideHover() {
    const h = $("hover");
    if (h) h.style.display = "none";
    $("tooltip").style.opacity = 0;
  }

  /* ------------------------------------------------------------------
     Menu
  ------------------------------------------------------------------- */
  let GAMES = [];
  let current = 0;
  let tabs = [];

  function buildMenu() {
    const tabsEl = $("tabs");
    tabsEl.textContent = "";
    tabs = GAMES.map((g, i) => {
      const b = document.createElement("button");
      b.className = "tab";
      b.type = "button";
      b.id = "tab-" + i;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-controls", "stage");
      b.textContent = g.short || g.name;
      if (g.short) b.setAttribute("aria-label", g.name);
      b.addEventListener("click", () => show(i, true));
      b.addEventListener("keydown", (e) => {
        const n = GAMES.length;
        const target = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: n - 1 }[e.key];
        if (target === undefined) return;
        e.preventDefault();
        const j = (target + n) % n;
        show(j, true);
        tabs[j].focus();
      });
      tabsEl.appendChild(b);
      return b;
    });
  }

  function show(i, animate) {
    current = i;
    tabs.forEach((t, j) => {
      t.setAttribute("aria-selected", j === i ? "true" : "false");
      t.tabIndex = j === i ? 0 : -1;
    });
    $("stage").setAttribute("role", "tabpanel");
    $("stage").setAttribute("aria-labelledby", "tab-" + i);
    hideHover();
    updateText(GAMES[i], animate);
    render(GAMES[i], animate);
  }

  /* ------------------------------------------------------------------
     Theme toggle
  ------------------------------------------------------------------- */
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  function effectiveTheme() {
    return document.documentElement.getAttribute("data-theme") || (darkQuery.matches ? "dark" : "light");
  }
  function updateToggle() {
    const dark = effectiveTheme() === "dark";
    const btn = $("themeToggle");
    btn.textContent = dark ? "Light mode" : "Dark mode";
    btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  }
  function setupTheme() {
    $("themeToggle").addEventListener("click", () => {
      const next = effectiveTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      store.set(KEY_THEME, next);
      updateToggle();
    });
    darkQuery.addEventListener("change", updateToggle);
    updateToggle();
  }

  /* ------------------------------------------------------------------
     Start
  ------------------------------------------------------------------- */
  function showError(err) {
    const el = $("status");
    el.className = "status error";
    el.setAttribute("role", "alert");
    const fromDisk = window.location.protocol === "file:";
    el.innerHTML =
      "<p><b>The data file couldn’t be loaded.</b></p>" +
      (fromDisk
        ? "<p>This page was opened straight from disk, and browsers block it from reading <code>data/games.json</code> that way.</p>"
        : `<p>Tried <code>data/games.json</code>: ${escapeHtml(err && err.message ? err.message : String(err))}.</p>`) +
      "<p>To view it locally, serve the <code>site</code> folder: run <code>python -m http.server 8000</code> inside <code>site/</code>, then open <code>http://localhost:8000</code>. " +
      "If the file is missing, build it first with <code>python -m pipeline.build --mock</code>.</p>";
  }

  function setNote() {
    const parts = [];
    if (META.placeholder) {
      parts.push("Every figure on this page is generated placeholder data for layout and testing. It is not real popularity, stock market or company data.");
    }
    parts.push(
      "Historical data, not live. Popularity is monthly and indexed so the launch month is 100. " +
      "Market value is shown as the daily % change since launch day, which equals the change in the share price " +
      "(the number of shares barely moves over a few months). Markets close at weekends and holidays, so the last close is carried across those days."
    );
    $("note").textContent = parts.join(" ");
  }

  async function init() {
    setupTheme();
    let data;
    try {
      const res = await fetch(`data/games.json?v=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
      if (!data || !data.meta || !Array.isArray(data.games) || data.games.length === 0) throw new Error("the file has no games");
    } catch (err) {
      showError(err);
      return;
    }

    META = data.meta;
    $("badge").hidden = !META.placeholder;
    $("legendPop").textContent = META.popularity_label;
    setNote();

    GAMES = pickGames(data.games, META.games_per_view || 6).map(prepare);
    buildMenu();
    $("status").hidden = true;
    $("content").hidden = false;
    show(0, true);

    let lastWidth = $("chart").clientWidth;
    let resizeTimer;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        const w = $("chart").clientWidth;
        if (w !== lastWidth) { lastWidth = w; render(GAMES[current], false); }
      }, 120);
    });
  }

  init();
})();
