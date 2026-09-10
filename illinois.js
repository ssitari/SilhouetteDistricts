// The Illinois page: five maps and one chart.
//
// A different question from the four national pages, so a different page. Those
// ask what the districts look like; this asks where a real electorate lands
// inside them, which is why it is the one page where colour carries a
// measurement rather than just keeping neighbours apart.
//
// That distinction is load-bearing. The five-hue cycle on the map pages means
// NOTHING by design, and a reader who saw a second map here in those same tints
// would reasonably read the two as the same encoding. So this page uses a
// diverging red-blue ramp that no other page uses, and says what it means.

import * as cfg from "./config.js";

const IL = cfg.ILLINOIS;
const svgNS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}) => {
  const n = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
const fmt = (n, d = 0) => n.toLocaleString(cfg.LOCALE, { maximumFractionDigits: d });
const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;

let DATA = null;

// ---------------------------------------------------------------------------
// The diverging ramp
//
// Piecewise about the midpoint rather than linear across the domain. An even
// 50-50 district has to land on the neutral middle stop, and the domain is not
// symmetric about 0.5 -- Illinois runs from 0.28 to 0.87 -- so a straight lerp
// would put the neutral colour at 0.58 and quietly call a Republican-leaning
// district blue.

const hex2rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const rgb2hex = (c) => "#" + c.map((v) =>
  Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");

function rampColor(v) {
  const stops = IL.RAMP.map(hex2rgb);
  const [lo, hi] = IL.DOMAIN, mid = IL.MIDPOINT;
  const half = (stops.length - 1) / 2;      // index of the neutral stop
  let t;
  if (v <= mid) t = half * (Math.max(v, lo) - lo) / (mid - lo);
  else t = half + half * (Math.min(v, hi) - mid) / (hi - mid);
  const i = Math.max(0, Math.min(stops.length - 2, Math.floor(t)));
  const f = t - i;
  return rgb2hex(stops[i].map((c, j) => c + f * (stops[i + 1][j] - c)));
}

// ---------------------------------------------------------------------------
// Maps

const ringPath = (ring) => {
  let d = "";
  for (let i = 0; i < ring.length; i++) {
    d += (i ? "L" : "M") + ring[i][0].toFixed(1) + "," + ring[i][1].toFixed(1);
  }
  return d + "Z";
};

function renderPanels() {
  const [x0, y0, x1, y1] = DATA.meta.bbox;
  const host = document.getElementById("panels");
  host.innerHTML = "";

  for (const p of DATA.panels) {
    const fig = document.createElement("figure");
    fig.className = "panel";

    const svg = el("svg", {
      viewBox: `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`,
      role: "img",
      "aria-label": `Illinois under the ${p.label} model, ${p.dem_seats} of ${p.seats} districts Democratic-leaning`,
    });
    // One flip for the whole drawing: projected y increases north, SVG y down.
    const flip = el("g", { transform: "scale(1,-1)" });
    for (const d of p.districts) {
      flip.appendChild(el("path", {
        d: d.rings.map(ringPath).join(""),
        "fill-rule": "evenodd",
        fill: rampColor(d.dem),
        stroke: "#ffffff",
        // Thin, and deliberately thinner than it looks like it wants to be.
        // These strokes are non-scaling, so they are 0.3 SCREEN pixels whatever
        // the panel's scale -- and Illinois's outward rings are about one pixel
        // wide at this size. At 0.6 the stroke ate the ring it was separating
        // and the whole outer half of that panel read as white.
        "stroke-width": 0.3,
        "vector-effect": "non-scaling-stroke",
        "data-model": p.key,
        "data-k": d.k,
      }));
    }
    svg.appendChild(flip);
    fig.appendChild(svg);

    const cap = document.createElement("figcaption");
    cap.innerHTML = `<strong>${p.label}</strong>
      <span>${p.dem_seats} of ${p.seats} lean D</span>`;
    fig.appendChild(cap);
    host.appendChild(fig);
  }
}

// ---------------------------------------------------------------------------
// The strip chart
//
// Every district under every model on one axis. The maps show where the lines
// fall; this shows what they do to the electorate, which is the only thing the
// five panels can actually be compared on.

function renderChart() {
  const host = document.getElementById("chart");
  host.innerHTML = "";

  const W = 900, rowH = 46, padL = 108, padR = 96, padT = 30;
  const H = padT + DATA.panels.length * rowH + 24;
  const [lo, hi] = IL.DOMAIN;
  const x = (v) => padL + ((v - lo) / (hi - lo)) * (W - padL - padR);

  const svg = el("svg", {
    viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Democratic two-party vote share of every Illinois district under each model",
  });

  // Axis ticks at every tenth, plus the 50-50 rule drawn heavier because it is
  // the only value on this axis that means anything on its own.
  for (let v = 0.3; v <= hi + 1e-9; v += 0.1) {
    svg.appendChild(el("line", {
      x1: x(v), x2: x(v), y1: padT - 8, y2: H - 22,
      stroke: "#e5e7eb", "stroke-width": 1,
    }));
    const t = el("text", {
      x: x(v), y: padT - 14, "text-anchor": "middle",
      "font-size": 11, fill: cfg.INK_MUTED,
    });
    t.textContent = pct(v, 0);
    svg.appendChild(t);
  }
  svg.appendChild(el("line", {
    x1: x(0.5), x2: x(0.5), y1: padT - 8, y2: H - 22,
    stroke: cfg.INK, "stroke-width": 1.25, "stroke-dasharray": "3 3",
  }));

  DATA.panels.forEach((p, i) => {
    const cy = padT + i * rowH + rowH / 2;

    const label = el("text", {
      x: padL - 14, y: cy + 4, "text-anchor": "end",
      "font-size": 12.5, fill: cfg.INK, "font-weight": 600,
    });
    label.textContent = p.label;
    svg.appendChild(label);

    // The row's own range, so a tight model reads as tight at a glance.
    const vals = p.districts.map((d) => d.dem);
    svg.appendChild(el("line", {
      x1: x(Math.min(...vals)), x2: x(Math.max(...vals)), y1: cy, y2: cy,
      stroke: "#d1d5db", "stroke-width": 1.5,
    }));

    for (const d of p.districts) {
      svg.appendChild(el("circle", {
        cx: x(d.dem), cy, r: 6.5,
        fill: rampColor(d.dem), stroke: "#6b7280", "stroke-width": 0.75,
        "data-model": p.key, "data-k": d.k,
      }));
    }

    const seats = el("text", {
      x: W - padR + 14, y: cy + 4, "text-anchor": "start",
      "font-size": 12, fill: cfg.INK_MUTED,
    });
    seats.textContent = `${p.dem_seats}D · ${p.seats - p.dem_seats}R`;
    svg.appendChild(seats);
  });

  host.appendChild(svg);
}

// ---------------------------------------------------------------------------
// Ramp legend

function renderRamp() {
  const [lo, hi] = IL.DOMAIN;
  const W = 260, H = 12;
  let stops = "";
  for (let i = 0; i <= 40; i++) {
    const v = lo + (i / 40) * (hi - lo);
    stops += `<rect x="${(i / 41) * W}" y="0" width="${W / 41 + 0.6}" height="${H}"
      fill="${rampColor(v)}" />`;
  }
  document.getElementById("ramp").innerHTML = `
    <svg width="${W}" height="${H + 18}" viewBox="0 0 ${W} ${H + 18}" aria-hidden="true">
      ${stops}
      <text x="0" y="${H + 14}" font-size="10.5" fill="${cfg.INK_MUTED}">${pct(lo, 0)} D</text>
      <text x="${W / 2}" y="${H + 14}" font-size="10.5" text-anchor="middle"
        fill="${cfg.INK_MUTED}">50%</text>
      <text x="${W}" y="${H + 14}" font-size="10.5" text-anchor="end"
        fill="${cfg.INK_MUTED}">${pct(hi, 0)} D</text>
    </svg>
    <span>${IL.RAMP_LABEL}</span>`;
}

// ---------------------------------------------------------------------------
// Table, so identity is never colour-alone

function renderTable() {
  const head = ["District", ...DATA.panels.map((p) => p.label)];
  const n = DATA.meta.seats;
  let rows = "";
  for (let k = 1; k <= n; k++) {
    rows += `<tr><td>${k}</td>` + DATA.panels.map((p) => {
      const d = p.districts.find((x) => x.k === k);
      return `<td>${d ? pct(d.dem) : "—"}</td>`;
    }).join("") + "</tr>";
  }
  const totals = `<tr class="tot"><td>Seats leaning D</td>` +
    DATA.panels.map((p) => `<td>${p.dem_seats} of ${p.seats}</td>`).join("") + "</tr>";
  document.getElementById("table").innerHTML = `
    <table class="districts">
      <thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows}${totals}</tbody>
    </table>`;
}

// ---------------------------------------------------------------------------
// Hover, shared by the maps and the chart

const tooltip = document.getElementById("tooltip");
let hovered = null;

function onMove(evt) {
  const t = evt.target;
  if (!(t instanceof SVGElement) || !t.dataset.k || !t.dataset.model) return clearHover();
  if (hovered !== t) {
    clearHover();
    hovered = t;
    t.setAttribute("stroke", cfg.HIGHLIGHT);
    t.setAttribute("stroke-width", 2.5);
  }
  const p = DATA.panels.find((x) => x.key === t.dataset.model);
  const d = p.districts.find((x) => x.k === +t.dataset.k);
  const row = (a, b) => `<div class="t-row"><span>${a}</span><span>${b}</span></div>`;
  tooltip.innerHTML = `
    <div class="t-state">${p.label} · district ${d.k}</div>
    ${row("Democratic", `${pct(d.dem)}`)}
    ${row("D votes", fmt(d.dem_votes))}
    ${row("R votes", fmt(d.rep_votes))}
    ${row("Population", fmt(d.population))}
    <div class="t-note">${d.dem >= 0.5 ? "Leans Democratic." : "Leans Republican."}</div>`;

  const box = document.getElementById("figure").getBoundingClientRect();
  tooltip.style.opacity = "1";
  const touch = evt.pointerType === "touch";
  const gap = touch ? 24 : 14;
  const x = evt.clientX - box.left, y = evt.clientY - box.top;
  tooltip.style.left = Math.max(0, Math.min(x + gap, box.width - tooltip.offsetWidth)) + "px";
  tooltip.style.top = Math.max(0, touch ? y - tooltip.offsetHeight - gap : y + gap) + "px";
}

function clearHover() {
  if (hovered) {
    // Chart dots and map districts carry different resting strokes.
    const isDot = hovered.tagName === "circle";
    hovered.setAttribute("stroke", isDot ? "#6b7280" : "#ffffff");
    hovered.setAttribute("stroke-width", isDot ? 0.75 : 0.3);
  }
  hovered = null;
  tooltip.style.opacity = "0";
}

// ---------------------------------------------------------------------------

function renderNav() {
  document.getElementById("nav").innerHTML = Object.entries(cfg.MODELS)
    .map(([key, m]) => `<a href="map.html?model=${key}">${m.title.split(" — ")[0]}</a>`)
    .join("") + `<span class="here aside" aria-current="page">Illinois</span>`;
}

async function init() {
  document.getElementById("title").textContent = IL.title;
  document.title = `${IL.title} · ${cfg.SITE_TITLE}`;
  document.getElementById("blurb").textContent = IL.blurb;
  document.getElementById("note").textContent = IL.note;
  document.getElementById("chart-note").textContent = IL.CHART_LABEL;
  document.getElementById("credit").innerHTML =
    `${cfg.DATA_CREDIT}${cfg.REPO_URL ? ` &middot; <a href="${cfg.REPO_URL}">${cfg.REPO_LABEL}</a>` : ""}`;
  renderNav();

  const res = await fetch(IL.data);
  if (!res.ok) throw new Error(`${IL.data}: ${res.status}. Serve over HTTP, not file://`);
  DATA = await res.json();

  if (!DATA.panels?.length || !DATA.meta?.bbox) {
    throw new Error(`${IL.data}: expected meta.bbox and a non-empty panels array. ` +
      `Rebuild with scripts/bundle_illinois.py.`);
  }

  renderRamp();
  renderPanels();
  renderChart();
  renderTable();

  const fig = document.getElementById("figure");
  fig.addEventListener("pointermove", onMove);
  fig.addEventListener("pointerdown", onMove);
  fig.addEventListener("pointerleave", (e) => {
    if (e.pointerType !== "touch") clearHover();
  });
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest?.("#figure")) clearHover();
  });
}

init().catch((err) => {
  document.getElementById("panels").innerHTML = `<div class="dataerr">${err.message}</div>`;
  console.error(err);
});
