/*
 * Trend Badge widget -- draws a price line and a Bullish / Bearish / Neutral
 * badge from prices the page supplies. No dependencies, no build step.
 *
 *   <script src="trend-widget.js"></script>
 *   <trend-badge name="ACME" closes="101,102,104,103,106,..."></trend-badge>
 *   <trend-badge name="ACME" src="/prices/acme.json"></trend-badge>
 *
 * The label describes the shape of the prices shown. It is not a forecast.
 */
(function (root) {
  "use strict";

  var Trend = root.Trend;
  if (!Trend || typeof Trend.classify !== "function") {
    throw new Error("trend-widget: the Trend scorer did not load.");
  }

  var VERSION = "1.0.0";
  var DEFAULT_BARS = 63; // about three months of trading days
  var MIN_CLOSES = 3;

  // ------------------------------------------------------------ reading data

  function toNumber(v) {
    if (typeof v === "number") return v;
    if (typeof v !== "string") return NaN;
    var s = v.trim().replace(/[$,_\s]/g, "");
    return s === "" ? NaN : Number(s);
  }

  // A date from a unix time (seconds or milliseconds), a Date or a string.
  function toDate(v) {
    if (v === null || v === undefined || v === "") return null;
    if (v instanceof Date) return isNaN(v.getTime()) ? null : v;
    if (typeof v === "number" || /^\d+(\.\d+)?$/.test(String(v).trim())) {
      var n = Number(v);
      if (!isFinite(n)) return null;
      return new Date(n < 1e12 ? n * 1000 : n);
    }
    var d = new Date(String(v).trim());
    return isNaN(d.getTime()) ? null : d;
  }

  function splitList(text) {
    return String(text).split(/[\s,;]+/).filter(Boolean);
  }

  function pick(obj, names) {
    for (var i = 0; i < names.length; i++) {
      if (obj[names[i]] !== undefined) return obj[names[i]];
    }
    return undefined;
  }

  var CLOSE_KEYS = ["close", "Close", "c", "price", "Price", "value", "Value", "nav", "NAV"];
  var DATE_KEYS = ["date", "Date", "time", "Time", "t", "timestamp", "day"];

  // CSV with an optional header. With a header, the "close" (or "adj close",
  // "price", "value") column is the price and a "date" column the date.
  // Without one: one column is prices, two or more are date then price.
  function parseCSV(text) {
    var lines = String(text).split(/\r?\n/).map(function (l) { return l.trim(); })
      .filter(function (l) { return l && l.charAt(0) !== "#"; });
    if (!lines.length) return { closes: [], dates: null };
    var sep = lines[0].indexOf(";") >= 0 && lines[0].indexOf(",") < 0 ? ";" :
              lines[0].indexOf("\t") >= 0 ? "\t" : ",";
    var rows = lines.map(function (l) {
      return l.split(sep).map(function (c) { return c.trim().replace(/^"|"$/g, ""); });
    });
    var head = rows[0];
    var hasHeader = head.some(function (c) { return /[a-z]/i.test(c) && isNaN(toNumber(c)) && !toDate(c); });
    var closeCol, dateCol = -1;
    if (hasHeader) {
      var low = head.map(function (c) { return c.toLowerCase(); });
      closeCol = ["close", "adj close", "adj_close", "price", "value", "nav", "navpu"]
        .map(function (k) { return low.indexOf(k); })
        .filter(function (i) { return i >= 0; })[0];
      if (closeCol === undefined) closeCol = head.length - 1;
      dateCol = ["date", "time", "timestamp", "day"]
        .map(function (k) { return low.indexOf(k); })
        .filter(function (i) { return i >= 0; })[0];
      if (dateCol === undefined) dateCol = -1;
      rows = rows.slice(1);
    } else if (head.length >= 2) {
      dateCol = 0;
      closeCol = 1;
    } else {
      closeCol = 0;
    }
    var points = rows.map(function (r) {
      return { close: r[closeCol], date: dateCol >= 0 ? r[dateCol] : null };
    });
    return { points: points };
  }

  // Text from a file or an attribute: JSON first, then CSV, then a bare list.
  function parseText(text) {
    var s = String(text || "").trim();
    if (!s) return { closes: [], dates: null };
    if (s.charAt(0) === "[" || s.charAt(0) === "{") {
      try { return JSON.parse(s); } catch (e) { /* not JSON: read it as CSV */ }
    }
    if (/\n/.test(s)) return parseCSV(s);
    return splitList(s).map(toNumber);
  }

  /**
   * Turn any supported input into { closes, dates, dropped }, oldest first.
   * Accepts: [101, 102], [[date, close], ...], [{date, close}, ...],
   * { closes: [...], dates: [...] }, or the result of parseCSV.
   */
  function normalize(input) {
    var points = [];
    if (typeof input === "string") input = parseText(input);
    if (input && !Array.isArray(input) && typeof input === "object") {
      if (Array.isArray(input.points)) {
        points = input.points;
      } else {
        var cl = pick(input, ["closes", "close", "prices", "values", "c"]);
        var dt = pick(input, ["dates", "date", "timestamps", "times", "t"]);
        if (typeof cl === "string") cl = splitList(cl);
        if (typeof dt === "string") dt = splitList(dt);
        cl = cl || [];
        points = cl.map(function (c, i) {
          return { close: c, date: Array.isArray(dt) ? dt[i] : null };
        });
      }
    } else if (Array.isArray(input)) {
      points = input.map(function (p) {
        if (Array.isArray(p)) return p.length >= 2 ? { date: p[0], close: p[1] } : { close: p[0] };
        if (p && typeof p === "object") return { close: pick(p, CLOSE_KEYS), date: pick(p, DATE_KEYS) };
        return { close: p, date: null };
      });
    }

    var closes = [], dates = [], dropped = 0, anyDate = false;
    for (var i = 0; i < points.length; i++) {
      var c = toNumber(points[i].close);
      if (!(isFinite(c) && c > 0)) { dropped++; continue; }
      var d = toDate(points[i].date);
      if (d) anyDate = true;
      closes.push(c);
      dates.push(d);
    }
    if (!anyDate) dates = null;

    // Newest-first files are common; the scorer needs oldest first.
    if (dates && dates.length > 1 && dates[0] && dates[dates.length - 1] &&
        dates[0].getTime() > dates[dates.length - 1].getTime()) {
      closes.reverse();
      dates.reverse();
    }
    return { closes: closes, dates: dates, dropped: dropped };
  }

  // ----------------------------------------------------------------- verdict

  function words(result) {
    if (!result) return { text: "Not enough data", tag: "", tone: "none" };
    var tag = "";
    if (result.label === "bullish" && result.pullback) tag = "pulling back";
    if (result.label === "bearish" && result.pullback) tag = "bouncing";
    if (result.label === "neutral" && result.lean) tag = "leaning " + result.lean;
    var text = result.label.charAt(0).toUpperCase() + result.label.slice(1);
    var tone = result.label === "bullish" ? "up" : result.label === "bearish" ? "down" : "flat";
    return { text: text, tag: tag, tone: tone };
  }

  /**
   * Score prices without drawing anything.
   * @param {*} input  any form normalize() accepts
   * @param {{bars?: number|"all"}} [options]
   */
  function judge(input, options) {
    options = options || {};
    var series = input && input.closes && input.dropped !== undefined ? input : normalize(input);
    var bars = options.bars === "all" ? series.closes.length :
               Math.max(MIN_CLOSES, Math.floor(Number(options.bars) || DEFAULT_BARS));
    var start = Math.max(0, series.closes.length - bars);
    var closes = series.closes.slice(start);
    var dates = series.dates ? series.dates.slice(start) : null;
    var result = closes.length >= MIN_CLOSES ? Trend.classify(closes) : null;
    var first = closes[0], last = closes[closes.length - 1];
    var w = words(result);
    return {
      label: result ? result.label : null,
      words: w.text + (w.tag ? ", " + w.tag : ""),
      tone: w.tone,
      tag: w.tag,
      result: result,
      closes: closes,
      dates: dates,
      first: first,
      last: last,
      change: closes.length > 1 ? last / first - 1 : null,
      bars: closes.length,
      dropped: series.dropped,
    };
  }

  // --------------------------------------------------------------- formatting

  function fmtPrice(x, currency, locale) {
    if (!isFinite(x)) return "";
    var digits = x >= 1 ? 2 : x >= 0.01 ? 4 : 6;
    try {
      var opts = { minimumFractionDigits: digits, maximumFractionDigits: digits };
      if (currency) { opts.style = "currency"; opts.currency = currency; }
      return new Intl.NumberFormat(locale || undefined, opts).format(x);
    } catch (e) {
      return (currency ? currency + " " : "") + x.toFixed(digits);
    }
  }

  function fmtPct(x, locale) {
    if (x === null || !isFinite(x)) return "";
    try {
      return new Intl.NumberFormat(locale || undefined, {
        style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: "exceptZero",
      }).format(x);
    } catch (e) {
      return (x > 0 ? "+" : "") + (x * 100).toFixed(1) + "%";
    }
  }

  function fmtDate(d, locale, withYear) {
    if (!d) return "";
    var opts = { month: "short", day: "numeric", timeZone: "UTC" };
    if (withYear) opts.year = "numeric";
    try { return new Intl.DateTimeFormat(locale || undefined, opts).format(d); }
    catch (e) { return d.toISOString().slice(0, 10); }
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  // ------------------------------------------------------------------ drawing

  var W = 300, H = 72, PAD = 3;

  function linePoints(closes) {
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var span = hi - lo || 1;
    var n = closes.length;
    return closes.map(function (c, i) {
      var x = n === 1 ? W / 2 : (i / (n - 1)) * W;
      var y = PAD + (1 - (c - lo) / span) * (H - 2 * PAD);
      return [Math.round(x * 100) / 100, Math.round(y * 100) / 100];
    });
  }

  var CSS = [
    ":host{--trend-up:#157a43;--trend-down:#c0392b;--trend-flat:#5f6873;",
    "--trend-bg:#ffffff;--trend-fg:#1d2330;--trend-muted:#5f6873;--trend-border:#dfe3e8;",
    "--trend-radius:12px;--trend-font:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;",
    "display:block;font-family:var(--trend-font);color:var(--trend-fg);}",
    ":host([layout=badge]){display:inline-block;vertical-align:middle;}",
    ":host([theme=dark]){--trend-up:#4cc38a;--trend-down:#ff7a6b;--trend-flat:#a0a9b4;",
    "--trend-bg:#161b22;--trend-fg:#e8ecf1;--trend-muted:#a0a9b4;--trend-border:#2d3541;}",
    "@media (prefers-color-scheme:dark){:host(:not([theme=light])){--trend-up:#4cc38a;",
    "--trend-down:#ff7a6b;--trend-flat:#a0a9b4;--trend-bg:#161b22;--trend-fg:#e8ecf1;",
    "--trend-muted:#a0a9b4;--trend-border:#2d3541;}}",
    ".card{background:var(--trend-bg);border:1px solid var(--trend-border);border-radius:var(--trend-radius);",
    "padding:14px 16px 12px;box-sizing:border-box;min-width:0;}",
    ".top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;}",
    ".name{font-weight:650;font-size:15px;overflow-wrap:anywhere;}",
    ".pill{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:650;line-height:1;",
    "padding:5px 10px;border-radius:999px;border:1px solid currentColor;white-space:nowrap;}",
    ".pill::before{content:'';width:7px;height:7px;border-radius:50%;background:currentColor;}",
    ".pill .tag{font-weight:500;opacity:.85;}",
    ".up{color:var(--trend-up);}.down{color:var(--trend-down);}.flat,.none{color:var(--trend-flat);}",
    ".price{margin-top:8px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;}",
    ".last{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums;}",
    ".chg{font-size:13px;color:var(--trend-muted);font-variant-numeric:tabular-nums;}",
    "svg{display:block;width:100%;height:72px;margin-top:8px;overflow:visible;touch-action:pan-y;}",
    ".line{fill:none;stroke:currentColor;stroke-width:2;vector-effect:non-scaling-stroke;",
    "stroke-linejoin:round;stroke-linecap:round;}",
    ".area{fill:currentColor;opacity:.10;stroke:none;}",
    ".cross{stroke:var(--trend-muted);stroke-width:1;vector-effect:non-scaling-stroke;opacity:0;}",
    ".dot{fill:currentColor;opacity:0;}",
    "svg.hover .cross,svg.hover .dot{opacity:1;}",
    ".note{margin-top:8px;font-size:11.5px;color:var(--trend-muted);line-height:1.4;}",
    ".msg{font-size:13px;color:var(--trend-muted);}",
  ].join("");

  function pillHTML(v) {
    var w = words(v.result);
    return '<span class="pill ' + w.tone + '" part="badge">' + esc(w.text) +
      (w.tag ? ' <span class="tag">· ' + esc(w.tag) + "</span>" : "") + "</span>";
  }

  function cardHTML(v, o) {
    var w = words(v.result);
    var pts = linePoints(v.closes);
    var line = pts.map(function (p) { return p[0] + "," + p[1]; }).join(" ");
    var area = "0," + H + " " + line + " " + W + "," + H;
    var d0 = v.dates && v.dates[0], d1 = v.dates && v.dates[v.dates.length - 1];
    var spanYears = d0 && d1 && d0.getUTCFullYear() !== d1.getUTCFullYear();
    var range = d0 && d1 ? fmtDate(d0, o.locale, spanYears) + " – " + fmtDate(d1, o.locale, true) : "";
    var label = (o.name ? o.name + ": " : "") + w.text + (w.tag ? ", " + w.tag : "") +
      ". Last price " + fmtPrice(v.last, o.currency, o.locale) + ", " +
      fmtPct(v.change, o.locale) + " over " + v.bars + " days.";
    var note = o.note === "off" ? "" :
      '<div class="note" part="note">' + (range ? esc(range) + " · " : "") +
      "Trend of the last " + v.bars + " days. Describes the past, not a forecast.</div>";
    return '<div class="card" part="card">' +
      '<div class="top">' + (o.name ? '<span class="name" part="name">' + esc(o.name) + "</span>" : "<span></span>") +
      pillHTML(v) + "</div>" +
      '<div class="price"><span class="last" part="price">' + esc(fmtPrice(v.last, o.currency, o.locale)) +
      '</span><span class="chg" part="change">' + esc(fmtPct(v.change, o.locale)) +
      " over " + v.bars + " days</span></div>" +
      '<svg class="' + w.tone + '" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img" aria-label="' +
      esc(label) + '"><polygon class="area" points="' + area + '"/>' +
      '<polyline class="line" points="' + line + '"/>' +
      '<line class="cross" x1="0" x2="0" y1="0" y2="' + H + '"/>' +
      '<circle class="dot" r="2.5" cx="0" cy="0"/></svg>' + note + "</div>";
  }

  // ------------------------------------------------------------ the element

  var Base = root.HTMLElement || function () {};

  function TrendBadgeClass() {
    // Built only where custom elements exist (browsers), so this file also
    // loads under Node for testing.
    return class TrendBadge extends Base {
      static get observedAttributes() {
        return ["closes", "dates", "src", "name", "currency", "locale", "bars", "layout", "note", "refresh"];
      }
      constructor() {
        super();
        this._shadow = this.attachShadow({ mode: "open" });
        this._data = null;
        this._token = 0;
        this._verdict = null;
        this._pending = false;
        this._timer = null;
      }
      connectedCallback() { this._schedule(); this._startTimer(); }
      disconnectedCallback() { this._stopTimer(); }
      attributeChangedCallback(name) {
        if (name === "refresh") { this._stopTimer(); this._startTimer(); }
        if (this.isConnected) this._schedule();
      }
      get data() { return this._data; }
      set data(v) { this._data = v; this._schedule(); }
      get verdict() { return this._verdict; }
      reload() { this._schedule(); }

      _startTimer() {
        var s = Number(this.getAttribute("refresh"));
        if (this.isConnected && this.getAttribute("src") && s >= 30) {
          var self = this;
          this._timer = setInterval(function () { self._schedule(); }, s * 1000);
        }
      }
      _stopTimer() { if (this._timer) clearInterval(this._timer); this._timer = null; }

      _schedule() {
        if (this._pending) return;
        this._pending = true;
        var self = this;
        Promise.resolve().then(function () { self._pending = false; self._load(); });
      }

      _load() {
        var token = ++this._token, self = this;
        var src = this.getAttribute("src");
        if (this._data) return this._show(normalize(this._data));
        if (src) {
          if (!this._verdict) this._message("Loading prices…");
          fetch(src, { cache: "no-cache" })
            .then(function (r) {
              if (!r.ok) throw new Error("HTTP " + r.status);
              return r.text();
            })
            .then(function (text) { if (token === self._token) self._show(normalize(parseText(text))); })
            .catch(function (err) {
              if (token !== self._token) return;
              // A failed load is never shown as a verdict.
              self._verdict = null;
              self._message("Prices could not be loaded.");
              self._emit("trenderror", { error: String(err && err.message || err) });
            });
          return;
        }
        var closes = this.getAttribute("closes");
        if (closes) {
          var dates = this.getAttribute("dates");
          return this._show(normalize({ closes: splitList(closes), dates: dates ? splitList(dates) : null }));
        }
        this._message("No prices given.");
      }

      _options() {
        return {
          name: this.getAttribute("name") || "",
          currency: this.getAttribute("currency") || "",
          locale: this.getAttribute("locale") || "",
          layout: this.getAttribute("layout") || "card",
          note: this.getAttribute("note") || "",
        };
      }

      _message(text) {
        var o = this._options();
        this._shadow.innerHTML = "<style>" + CSS + "</style>" + (o.layout === "badge" ?
          '<span class="pill none" part="badge">' + esc(text) + "</span>" :
          '<div class="card" part="card">' + (o.name ? '<div class="name" part="name">' + esc(o.name) + "</div>" : "") +
          '<div class="msg">' + esc(text) + "</div></div>");
      }

      _show(series) {
        var bars = this.getAttribute("bars");
        var v = judge(series, { bars: bars === "all" ? "all" : bars });
        if (!v.result) {
          this._verdict = null;
          this._message(v.closes.length ? "Not enough data." : "No prices given.");
          return;
        }
        this._verdict = v;
        var o = this._options();
        this._shadow.innerHTML = "<style>" + CSS + "</style>" + (o.layout === "badge" ? pillHTML(v) : cardHTML(v, o));
        this.setAttribute("data-label", v.label);
        if (o.layout !== "badge") this._hover(v, o);
        this._emit("trend", v);
      }

      _hover(v, o) {
        var svg = this._shadow.querySelector("svg");
        var last = this._shadow.querySelector(".last");
        var chg = this._shadow.querySelector(".chg");
        var cross = svg.querySelector(".cross"), dot = svg.querySelector(".dot");
        var pts = linePoints(v.closes);
        var restLast = last.textContent, restChg = chg.textContent;
        function move(ev) {
          var box = svg.getBoundingClientRect();
          if (!box.width) return;
          var f = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
          var i = Math.round(f * (v.closes.length - 1));
          var p = pts[i];
          cross.setAttribute("x1", p[0]); cross.setAttribute("x2", p[0]);
          dot.setAttribute("cx", p[0]); dot.setAttribute("cy", p[1]);
          svg.classList.add("hover");
          last.textContent = fmtPrice(v.closes[i], o.currency, o.locale);
          var d = v.dates && v.dates[i];
          chg.textContent = d ? fmtDate(d, o.locale, true) : "day " + (i + 1) + " of " + v.closes.length;
        }
        function leave() {
          svg.classList.remove("hover");
          last.textContent = restLast; chg.textContent = restChg;
        }
        svg.addEventListener("pointermove", move);
        svg.addEventListener("pointerdown", move);
        svg.addEventListener("pointerleave", leave);
      }

      _emit(type, detail) {
        if (typeof CustomEvent === "function") {
          this.dispatchEvent(new CustomEvent(type, { detail: detail, bubbles: true }));
        }
      }
    };
  }

  if (root.customElements && root.HTMLElement && !root.customElements.get("trend-badge")) {
    root.customElements.define("trend-badge", TrendBadgeClass());
  }

  /** Put a widget inside `target` (an element or a CSS selector). */
  function mount(target, data, attrs) {
    var host = typeof target === "string" ? root.document.querySelector(target) : target;
    if (!host) throw new Error("trend-widget: no element matches " + target);
    var el = root.document.createElement("trend-badge");
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    if (data !== undefined && data !== null) el.data = data;
    host.appendChild(el);
    return el;
  }

  root.TrendWidget = {
    version: VERSION,
    judge: judge,
    mount: mount,
    normalize: normalize,
    parseText: parseText,
    words: words,
  };
})(typeof self !== "undefined" ? self : this);
