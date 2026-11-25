/* Advent of Code results site. Renders data.json with plain DOM calls (textContent only: answers,
   error output and language names are data, never markup). */
(function () {
  "use strict";

  var DATA = null;
  var main = document.getElementById("main");
  var tip = document.getElementById("tip");

  // ---------------------------------------------------------------- helpers
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    });
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, kid) {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) return kid.forEach(function (k) { append(el, k); });
    el.appendChild(typeof kid === "object" ? kid : document.createTextNode(String(kid)));
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  function fmtT(s) {
    if (s === null || s === undefined) return "–";
    if (s < 0.001) return Math.round(s * 1e6) + " µs";
    if (s < 1) return (s * 1000).toFixed(s < 0.01 ? 2 : 1) + " ms";
    return s < 100 ? s.toFixed(2) + " s" : Math.round(s) + " s";
  }
  function fmtX(x) {
    if (x === null || x === undefined) return "–";
    if (x < 10) return x.toFixed(2) + "×";
    if (x < 100) return x.toFixed(1) + "×";
    return Math.round(x).toLocaleString("en") + "×";
  }
  function fmtMB(m) {
    if (m === null || m === undefined) return "–";
    return m < 100 ? m.toFixed(1) + " MB" : Math.round(m).toLocaleString("en") + " MB";
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s"); }

  var VERDICT = {
    correct: ["✓", "Correct"], unchecked: ["?", "Unchecked"], wrong: ["✗", "Wrong answer"],
    build_failed: ["✗", "Build failed"], runtime_error: ["✗", "Crashed"], timeout: ["✗", "Timed out"],
    bad_output: ["✗", "Bad output"], no_toolchain: ["–", "No toolchain"]
  };
  function verdict(r) {
    var v = VERDICT[r.verdict] || ["?", r.verdict];
    return h("span", { class: "v v-" + r.verdict }, h("span", { "aria-hidden": "true", text: v[0] }), h("b", { text: v[1] }));
  }
  function kindClass(k) { return "k-" + (k || "native"); }
  var KINDS = [["native", "Compiled to native code"], ["vm", "Bytecode / JIT runtime"], ["interpreted", "Interpreted"]];

  // ---------------------------------------------------------------- tooltip
  function showTip(build, x, y) {
    clear(tip);
    build(tip);
    tip.hidden = false;
    var w = tip.offsetWidth, hgt = tip.offsetHeight;
    var left = Math.min(x + 14, window.innerWidth - w - 8);
    var top = y + 16 + hgt > window.innerHeight ? y - hgt - 12 : y + 16;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }
  function hideTip() { tip.hidden = true; }
  function attachTip(el, build) {
    el.addEventListener("pointermove", function (e) { showTip(build, e.clientX, e.clientY); });
    el.addEventListener("pointerleave", hideTip);
    el.addEventListener("focus", function () { var r = el.getBoundingClientRect(); showTip(build, r.left + 120, r.top); });
    el.addEventListener("blur", hideTip);
  }

  // ---------------------------------------------------------------- sortable table
  function table(cols, rows, sortKey, sortDir, caption) {
    var state = { key: sortKey, dir: sortDir || 1 };
    var wrap = h("div", { class: "tablewrap" });
    function draw() {
      clear(wrap);
      var sorted = rows.slice();
      var col = cols.filter(function (c) { return c.key === state.key; })[0];
      if (col && col.sort !== false) {
        sorted.sort(function (a, b) {
          var x = col.value ? col.value(a) : a[col.key], y = col.value ? col.value(b) : b[col.key];
          var nx = x === null || x === undefined, ny = y === null || y === undefined;
          if (nx || ny) return nx === ny ? 0 : nx ? 1 : -1;
          return (x < y ? -1 : x > y ? 1 : 0) * state.dir;
        });
      }
      var head = h("tr");
      cols.forEach(function (c) {
        var th = h("th", { scope: "col", class: c.num ? "num" : "" });
        if (c.sort === false) th.textContent = c.label;
        else {
          th.setAttribute("aria-sort", state.key === c.key ? (state.dir > 0 ? "ascending" : "descending") : "none");
          th.appendChild(h("button", { type: "button", text: c.label, onclick: function () {
            state.dir = state.key === c.key ? -state.dir : (c.first || 1);
            state.key = c.key; draw();
          } }));
        }
        head.appendChild(th);
      });
      var body = h("tbody");
      sorted.forEach(function (r, i) {
        var tr = h("tr");
        cols.forEach(function (c) { tr.appendChild(h("td", { class: (c.num ? "num " : "") + (c.cls || "") }, c.render(r, i))); });
        body.appendChild(tr);
      });
      wrap.appendChild(h("table", null, caption ? h("caption", { class: "note", text: caption, hidden: true }) : null,
        h("thead", null, head), body));
    }
    draw();
    return wrap;
  }

  // ---------------------------------------------------------------- leaderboard chart
  var TICKS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 100000];
  var DECADES = [1, 10, 100, 1000, 10000, 100000];

  function leaderChart(rows, metric) {
    var vals = rows.filter(function (r) { return r[metric] !== null && r[metric] !== undefined; })
      .sort(function (a, b) { return a[metric] - b[metric]; });
    var unranked = rows.filter(function (r) { return r[metric] === null || r[metric] === undefined; });
    if (!vals.length) return h("p", { class: "note", text: "No correct results to rank yet." });
    var max = vals[vals.length - 1][metric];
    var top = TICKS.filter(function (t) { return t >= max; })[0] || Math.ceil(max);
    if (window.innerWidth < 620) top = DECADES.filter(function (t) { return t >= max; })[0] || top;
    if (top <= 1) top = 2;
    var ticks = (window.innerWidth < 620 ? DECADES : TICKS).filter(function (t) { return t <= top; });
    if (ticks.indexOf(1) < 0) ticks.unshift(1);
    function pos(v) { return Math.max(0, Math.log(v) / Math.log(top)) * 100; }

    var chart = h("div", { class: "chart", role: "list", "aria-label": "Languages ranked by " + (metric === "slowdown" ? "speed" : "memory use") });
    var scale = h("div", { class: "scale" });
    ticks.forEach(function (t) { scale.appendChild(h("span", { style: "left:" + pos(t) + "%", text: fmtX(t).replace(/\.00|\.0(?=×)/, "") })); });
    chart.appendChild(h("div", { class: "axis", "aria-hidden": "true" }, h("span"), scale, h("span")));

    vals.forEach(function (r, i) {
      var track = h("div", { class: "track" });
      ticks.forEach(function (t) { track.appendChild(h("span", { class: "tick" + (t === 1 ? " base" : ""), style: "left:" + pos(t) + "%" })); });
      var p = pos(r[metric]);
      track.appendChild(h("span", { class: "stem", style: "left:0;width:" + p + "%" }));
      track.appendChild(h("span", { class: "dot", style: "left:" + p + "%" }));
      var row = h("div", { class: "crow " + kindClass(r.kind), role: "listitem", tabindex: "0" },
        h("span", { class: "name" }, h("span", { class: "swatch" }), r.name), track, h("span", { class: "val", text: fmtX(r[metric]) }));
      attachTip(row, function (t) {
        t.appendChild(h("strong", { text: r.name }));
        t.appendChild(h("div", { text: "Speed: " + (i === 0 && r.slowdown <= 1.0001 ? "fastest" : fmtX(r.slowdown) + " the fastest") + " (typical run " + fmtT(r.median_seconds) + ")" }));
        t.appendChild(h("div", { text: "Memory: " + fmtX(r.mem_ratio) + " the smallest" }));
        t.appendChild(h("div", { class: "k", text: r.ok + " of " + plural(r.days, "day") + " correct" + (r.wins ? " · " + plural(r.wins, "win") : "") }));
      });
      chart.appendChild(row);
    });

    var out = h("div", null, chart,
      h("p", { class: "axis-title", text: (metric === "slowdown"
        ? "Geometric mean of (median run time ÷ fastest correct solution) across days. Log scale; the left line is 1×, the fastest possible."
        : "Geometric mean of (peak memory ÷ smallest correct solution) across days. Log scale; the left line is 1×.") }));
    if (unranked.length) out.appendChild(h("p", { class: "note", text: "Not ranked (no correct result yet): " + unranked.map(function (r) { return r.name; }).join(", ") + "." }));
    return out;
  }

  function legend() {
    return h("div", { class: "legend", "aria-label": "Colour key" }, KINDS.map(function (k) {
      return h("span", { class: "k-" + k[0] }, h("i"), k[1]);
    }));
  }

  // ---------------------------------------------------------------- source dialog
  var dlg = document.getElementById("source");
  function openSource(view, row) {
    var path = "src/" + view.year + "/day" + pad(view.day) + "/" + row.id + "/" + row.file;
    document.getElementById("source-title").textContent = row.name + " · " + view.year + " day " + view.day;
    var code = document.getElementById("source-code");
    code.textContent = "Loading…";
    var gh = document.getElementById("source-gh");
    if (DATA.repo) { gh.href = "https://github.com/" + DATA.repo + "/blob/main/" + view.year + "/day" + pad(view.day) + "/" + row.id + "/" + row.file; gh.hidden = false; }
    else gh.hidden = true;
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
    fetch(path).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (t) { code.textContent = t; })
      .catch(function () { code.textContent = "Could not load the source file."; });
  }
  document.getElementById("source-copy").addEventListener("click", function () {
    var text = document.getElementById("source-code").textContent;
    if (navigator.clipboard) navigator.clipboard.writeText(text).catch(function () {});
  });

  // ---------------------------------------------------------------- pages
  function yearBar(active) {
    var bar = document.getElementById("yearbar");
    clear(bar);
    DATA.years.forEach(function (y) {
      bar.appendChild(h("a", { href: "#/" + y.year, "aria-current": String(active) === String(y.year) ? "page" : null, text: y.year }));
    });
    if (DATA.years.length > 1) bar.appendChild(h("a", { href: "#/all", "aria-current": active === "all" ? "page" : null, text: "All years" }));
  }

  function leaderboardColumns() {
    return [
      { key: "rank", label: "#", num: true, render: function (r, i) { return r.slowdown === null ? "–" : String(r._rank); }, value: function (r) { return r._rank || null; } },
      { key: "name", label: "Language", render: function (r) { return h("span", { class: kindClass(r.kind) }, h("span", { class: "swatch" }), r.name); } },
      { key: "slowdown", label: "Speed vs fastest", num: true, render: function (r) { return fmtX(r.slowdown); } },
      { key: "median_seconds", label: "Typical run", num: true, render: function (r) { return fmtT(r.median_seconds); } },
      { key: "mem_ratio", label: "Memory vs smallest", num: true, render: function (r) { return fmtX(r.mem_ratio); } },
      { key: "build_seconds", label: "Build", num: true, render: function (r) { return r.build_seconds ? fmtT(r.build_seconds) : "none"; } },
      { key: "ok", label: "Correct days", num: true, first: -1, render: function (r) { return r.ok + " / " + r.days; } },
      { key: "wins", label: "Wins", num: true, first: -1, render: function (r) { return String(r.wins); } },
      { key: "failed", label: "Failures", num: true, render: function (r) { return String(r.failed + r.wrong); }, value: function (r) { return r.failed + r.wrong; } }
    ];
  }

  function overviewPage(label, board, views, year) {
    var wrap = h("div");
    var ranked = board.filter(function (r) { return r.slowdown !== null; });
    ranked.forEach(function (r, i) { r._rank = i + 1; });
    var totalSol = 0, okSol = 0;
    board.forEach(function (r) { totalSol += r.days; okSol += r.ok; });

    wrap.appendChild(h("h2", { text: label === "All years" ? "All years" : "Advent of Code " + label }));
    if (ranked.length) {
      var fast = ranked[0], slow = ranked[ranked.length - 1];
      wrap.appendChild(h("p", { class: "lede", text:
        fast.name + " is the fastest across " + plural(views.length, "day") + ", and " + slow.name + " is the slowest at " + fmtX(slow.slowdown) +
        " the fastest solution's time. " + okSol + " of " + plural(totalSol, "solution") + " produced a correct or unchecked answer." }));
    }

    var metric = { v: "slowdown" };
    var chartHost = h("div");
    var segSpeed = h("button", { class: "ghost", type: "button", "aria-pressed": "true", text: "Speed" });
    var segMem = h("button", { class: "ghost", type: "button", "aria-pressed": "false", text: "Memory" });
    function draw() {
      clear(chartHost);
      chartHost.appendChild(leaderChart(board, metric.v));
      segSpeed.setAttribute("aria-pressed", String(metric.v === "slowdown"));
      segMem.setAttribute("aria-pressed", String(metric.v === "mem_ratio"));
    }
    segSpeed.addEventListener("click", function () { metric.v = "slowdown"; draw(); });
    segMem.addEventListener("click", function () { metric.v = "mem_ratio"; draw(); });
    draw();

    wrap.appendChild(h("div", { class: "panel" },
      h("div", { class: "toolbar" }, h("span", { class: "seg", role: "group", "aria-label": "Metric" }, segSpeed, segMem), legend()),
      chartHost));

    wrap.appendChild(h("h3", { text: "Leaderboard table" }));
    wrap.appendChild(table(leaderboardColumns(), board, "rank", 1));

    wrap.appendChild(h("h2", { text: "Days" }));
    wrap.appendChild(daysList(views));
    return wrap;
  }

  function daysList(views) {
    var list = h("div", { class: "tablewrap daylist" });
    views.slice().sort(function (a, b) { return a.year === b.year ? a.day - b.day : b.year - a.year; }).forEach(function (v) {
      var good = v.rows.filter(function (r) { return r.verdict === "correct" || r.verdict === "unchecked"; }).length;
      var fastest = v.rows.filter(function (r) { return r.rank === 1; })[0];
      var answers = v.expected.map(function (e, i) { return "Part " + (i + 1) + ": " + (e.answer || "?"); }).join("   ");
      list.appendChild(h("a", { class: "row", href: "#/" + v.year + "/day/" + v.day },
        h("span", { class: "d", text: String(v.day) }),
        h("span", null, h("div", { class: "t", text: v.title || "Day " + v.day }), h("div", { class: "ans", text: answers })),
        h("span", { class: "right meta" }, fastest ? "Fastest: " + fastest.name + " " + fmtT(fastest.median) : "No ranked result", h("br"),
          good + " of " + plural(v.rows.length, "language") + " correct")));
    });
    return list;
  }

  var HOW = { verified: "Accepted by adventofcode.com", consensus: "Most languages agree", none: "No reference yet" };

  function dayPage(year, day) {
    var yd = DATA.years.filter(function (y) { return String(y.year) === String(year); })[0];
    var v = yd && yd.days.filter(function (d) { return d.day === Number(day); })[0];
    if (!v) return notFound();
    var wrap = h("div");
    wrap.appendChild(h("p", { class: "crumbs" }, h("a", { href: "#/" + v.year, text: v.year }), " / Day " + v.day));
    wrap.appendChild(h("h2", { text: "Day " + v.day + (v.title ? ": " + v.title : "") }));

    var answers = h("div", { class: "answers" });
    v.expected.forEach(function (e, i) {
      answers.appendChild(h("div", { class: "answer" },
        h("div", { class: "label", text: "Part " + (i + 1) }),
        h("div", { class: "value", text: e.answer || "unknown" }),
        h("div", { class: "how", text: HOW[e.source || "none"] })));
    });
    if (v.parts < 2) answers.appendChild(h("div", { class: "answer" }, h("div", { class: "label", text: "Part 2" }),
      h("div", { class: "how", text: "Not published yet. It appears once part 1 is solved on adventofcode.com." })));
    wrap.appendChild(answers);

    var times = v.rows.map(function (r) { return r.median; }).filter(function (t) { return t; });
    var tmin = Math.min.apply(null, times), tmax = Math.max.apply(null, times);
    function bar(t) {
      if (!t || !(tmax > tmin)) return null;
      var w = 4 + 96 * Math.log(t / tmin) / Math.log(tmax / tmin);
      return h("span", { class: "mini", style: "width:" + Math.round(w * 1.2) + "px" });
    }
    var cols = [
      { key: "rank", label: "#", num: true, render: function (r) { return r.rank ? String(r.rank) : "–"; }, value: function (r) { return r.rank; } },
      { key: "name", label: "Language", render: function (r) {
        return h("span", { class: kindClass(r.kind) }, h("span", { class: "swatch" }), r.name, h("div", { class: "sub", text: r.version || "" })); } },
      { key: "verdict", label: "Result", render: function (r) {
        return h("div", null, verdict(r), r.error && r.verdict !== "correct" ? h("details", { class: "err" }, h("summary", { text: "Details" }), h("pre", { text: r.error })) : null,
          r.repairs ? h("div", { class: "sub", text: "Fixed after " + plural(r.repairs, "retry") }) : null); } },
      { key: "median", label: "Median time", num: true, cls: "k", render: function (r) { return h("span", { class: kindClass(r.kind) }, fmtT(r.median), bar(r.median)); } },
      { key: "slowdown", label: "vs fastest", num: true, render: function (r) { return fmtX(r.slowdown); } },
      { key: "min", label: "Best run", num: true, render: function (r) { return fmtT(r.min); } },
      { key: "cold", label: "First run", num: true, render: function (r) { return fmtT(r.cold); } },
      { key: "rss_mb", label: "Peak memory", num: true, render: function (r) { return fmtMB(r.rss_mb); } },
      { key: "build_seconds", label: "Build", num: true, render: function (r) { return r.build_seconds ? fmtT(r.build_seconds) : "none"; } },
      { key: "output", label: "Printed", cls: "ans", sort: false, render: function (r) { return r.output.join(" / "); } },
      { key: "src", label: "Code", sort: false, render: function (r) { return h("button", { class: "link", type: "button", text: "View", onclick: function () { openSource(v, r); } }); } }
    ];
    wrap.appendChild(h("div", { class: "panel", style: "margin-top:14px" }, h("div", { class: "toolbar" }, legend()),
      table(cols, v.rows, "rank", 1)));

    var rn = v.runner || {};
    var parts = [];
    if (rn.cpu) parts.push(rn.cpu + (rn.cores ? ", " + plural(rn.cores, "core") : ""));
    if (rn.os) parts.push(rn.os);
    wrap.appendChild(h("p", { class: "note", text: "Times are the median of repeated runs of the whole process, startup included, so runtimes with a slow start (JVM, .NET, Julia, Elixir) pay for it. The first run is shown separately. " +
      (parts.length ? "Measured on " + parts.join(" · ") + ". " : "") + (v.model ? "Code written by " + v.model + "." : "") }));
    return wrap;
  }

  function notFound() {
    return h("div", { class: "empty" }, h("h2", { text: "Nothing here" }), h("p", null, "That page does not exist. ", h("a", { href: "#/", text: "Back to the overview" }), "."));
  }

  function emptyPage() {
    return h("div", { class: "empty" }, h("h2", { text: "No results yet" }),
      h("p", { text: "Puzzles unlock at midnight US Eastern on December 1. The workflow fetches each day, writes the solutions, benchmarks them and publishes the results here." }));
  }

  // ---------------------------------------------------------------- routing
  function route() {
    hideTip();
    var parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
    clear(main);
    if (!DATA.years.length) { yearBar(null); main.appendChild(emptyPage()); return; }
    var year = parts[0];
    var page;
    if (parts[1] === "day" && parts[2]) { yearBar(year); page = dayPage(year, parts[2]); }
    else if (year === "all") {
      yearBar("all");
      var all = []; DATA.years.forEach(function (y) { all = all.concat(y.days); });
      page = overviewPage("All years", DATA.overall, all);
    } else {
      var yd = DATA.years.filter(function (y) { return String(y.year) === String(year); })[0] || DATA.years[0];
      yearBar(yd.year);
      page = overviewPage(String(yd.year), yd.leaderboard, yd.days, yd.year);
    }
    main.appendChild(page);
    window.scrollTo(0, 0);
    document.title = "Advent of Code in every language";
  }

  // ---------------------------------------------------------------- theme
  var root = document.documentElement;
  try { var saved = localStorage.getItem("aoc-theme"); if (saved) root.setAttribute("data-theme", saved); } catch (e) { /* storage may be unavailable */ }
  document.getElementById("theme").addEventListener("click", function () {
    var dark = root.getAttribute("data-theme") === "dark" ||
      (!root.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
    var next = dark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("aoc-theme", next); } catch (e) { /* ignore */ }
  });

  // ---------------------------------------------------------------- boot
  fetch("data.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (d) {
    DATA = d;
    if (d.repo) { var a = document.getElementById("repo-link"); a.href = "https://github.com/" + d.repo; a.hidden = false; }
    var n = d.languages.length;
    document.getElementById("tagline").textContent = "Every puzzle solved in " + n + " languages by Claude, and timed on the same input.";
    var when = new Date(d.generated_at);
    document.getElementById("foot-note").textContent = "Updated " + (isNaN(when) ? d.generated_at : when.toLocaleString()) +
      ". Puzzle text and personal inputs stay private; this site shows only answers, timings and code.";
    window.addEventListener("hashchange", route);
    route();
  }).catch(function () {
    main.appendChild(h("div", { class: "empty" }, h("h2", { text: "Could not load results" }), h("p", { text: "data.json is missing. Run `python3 -m harness site` and serve the dist folder over HTTP." })));
  });
})();
