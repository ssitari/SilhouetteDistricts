// Engine for the nested-silhouette district map. Edit config.js, not this file.
//
// No D3, and no projection code, because neither is needed: the solver emits
// coordinates already projected into equal-area metres, so drawing is a viewBox
// and a y-flip. That keeps the page dependency-free.
//
// The one idea worth knowing before reading anything below:
//
//   A district is never drawn as a ring. Each district k is drawn as a SOLID
//   copy of the state outline scaled by breaks[k], painted back to front from
//   the largest to the smallest. District k-1 lands on top of district k and
//   hides its middle, so what survives on screen is the annulus -- with no
//   boolean geometry, no even-odd paths, and one <path> per lobe reused by
//   <use> for all 435 districts.
//
//   Hit-testing falls out of the same trick. The topmost element under the
//   pointer is the smallest copy containing that point, which is exactly the
//   district the point belongs to. And re-filling that one <use> on hover
//   repaints only the band, because the inner copies still cover the rest.

import * as cfg from "./config.js";

const svgNS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}) => {
  const n = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
const fmt = (n, d = 0) => n.toLocaleString(cfg.LOCALE, { maximumFractionDigits: d });

// {placeholder} substitution for every label in config.js. An unknown key is
// left on screen verbatim rather than replaced with "undefined": a reuser who
// mistypes {region} should see {region} and know where to look.
const sub = (tpl, vals) =>
  String(tpl).replace(/\{(\w+)\}/g, (m, k) => (k in vals ? vals[k] : m));

let DATA = null;

// View state lives in the query string so a particular reading of the map --
// the grid sorted by lopsidedness -- can be linked to directly rather than
// described in prose.
const params = new URLSearchParams(location.search);
const oneOf = (v, allowed, fallback) => (allowed.includes(v) ? v : fallback);
let view = oneOf(params.get("view"), ["map", "grid"], cfg.DEFAULT_VIEW);

function syncURL() {
  const q = new URLSearchParams();
  if (view !== cfg.DEFAULT_VIEW) q.set("view", view);
  const s = q.toString();
  history.replaceState(null, "", s ? `?${s}` : location.pathname);
}

// ---------------------------------------------------------------------------
// Geometry helpers

// Scaling a shape about a fixed anchor is translate(a(1-s)) then scale(s) --
// the SVG transform does the arithmetic, so the outline ships once per lobe.
const scaleAbout = ([ax, ay], s) =>
  `translate(${((1 - s) * ax).toFixed(2)},${((1 - s) * ay).toFixed(2)}) scale(${s.toFixed(6)})`;

const pathData = (outline) => {
  let d = "";
  for (let i = 0; i < outline.length; i++) {
    d += (i ? "L" : "M") + outline[i][0].toFixed(1) + "," + outline[i][1].toFixed(1);
  }
  return d + "Z";
};

const bboxOf = (state) => {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const lobe of state.lobes) {
    for (const [x, y] of lobe.outline) {
      if (x < x0) x0 = x; if (x > x1) x1 = x;
      if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
  }
  return [x0, y0, x1, y1];
};

const ringRatio = (state) => {
  const b = state.breaks;
  let lo = Infinity, hi = 0;
  for (let k = 1; k < b.length; k++) {
    const w = b[k] - b[k - 1];
    if (w < lo) lo = w;
    if (w > hi) hi = w;
  }
  return lo > 0 ? hi / lo : 1;
};

// ---------------------------------------------------------------------------
// Colour
//
// Five hues, cycling every five districts, carrying no meaning of their own --
// they exist to keep neighbours apart. Each state starts at its own slot in the
// cycle (baked into the bundle; see config.js) so that one hue does not
// dominate the national map and neighbouring states do not fuse along a shared
// border. Fill and stroke always move together: the tints carry mass, the
// strokes carry the boundaries.

const offsetFor = (state) => {
  const off = DATA.meta.color_offsets;
  const v = off ? off[state.usps] : undefined;
  return v === undefined ? cfg.CYCLE_FALLBACK_OFFSET : v;
};

const slotFor = (state, k) => (k - 1 + offsetFor(state)) % cfg.FILLS.length;
const fillFor = (state, k) => cfg.FILLS[slotFor(state, k)];
const strokeFor = (state, k) => cfg.STROKES[slotFor(state, k)];

// ---------------------------------------------------------------------------
// Drawing one state

let uid = 0;

function drawState(parent, defs, state, { transform = null } = {}) {
  const g = el("g", { class: "state", "data-usps": state.usps });
  if (transform) g.setAttribute("transform", transform);

  state.lobes.forEach((lobe, li) => {
    const id = `o${uid++}`;
    defs.appendChild(el("path", { id, d: pathData(lobe.outline) }));

    // Clip the whole lobe group rather than intersecting each ring. On a
    // concave lobe a shrunk copy can cross its own boundary -- 6% of ring area
    // in Michigan, which reads as districts spilling into Lake Huron -- and
    // clipping the group costs nothing while keeping the data as outline plus
    // scale factors.
    const cp = el("clipPath", { id: `c${id}`, clipPathUnits: "userSpaceOnUse" });
    cp.appendChild(el("use", { href: `#${id}` }));
    defs.appendChild(cp);

    const lg = el("g", { "clip-path": `url(#c${id})` });
    for (let k = state.seats; k >= 1; k--) {
      const u = el("use", {
        href: `#${id}`,
        transform: scaleAbout(lobe.anchor, state.breaks[k]),
        fill: fillFor(state, k),
        // Each copy carries its own stroke, which lands on that district's
        // OUTER edge and survives because the next district in is smaller. The
        // fills alone sit below the categorical-contrast floor by design, so
        // these hairlines are what actually separates one ring from the next.
        stroke: strokeFor(state, k),
        "stroke-width": cfg.STROKE_WIDTH,
        "vector-effect": "non-scaling-stroke",
        "data-usps": state.usps,
        "data-k": k,
      });
      lg.appendChild(u);
    }
    g.appendChild(lg);

    // The lobe's own boundary, above the fills and OUTSIDE the clip. The
    // outermost district already strokes this line, but clipped -- a stroke
    // straddles its path, so clipping halves it. Redrawing it unclipped at full
    // weight keeps the silhouette, which is the whole conceit, crisp. It takes
    // the outermost district's colour so the state edge stays part of the
    // cycle. vector-effect keeps it one pixel at every zoom and in both views,
    // which matters because the grid view scales states by wildly different
    // factors.
    g.appendChild(el("use", {
      href: `#${id}`, fill: "none", stroke: strokeFor(state, state.seats),
      "stroke-width": cfg.OUTLINE_WIDTH, "vector-effect": "non-scaling-stroke",
      "pointer-events": "none",
    }));
  });

  parent.appendChild(g);
  return g;
}

// ---------------------------------------------------------------------------
// The two views

function renderMap(root, defs) {
  const [x0, y0, x1, y1] = DATA.meta.frame_bbox;
  const svg = el("svg", {
    viewBox: `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`,
    role: "img",
    "aria-label": sub(cfg.ARIA_MAP, { units: DATA.meta.seats_total }),
  });
  svg.appendChild(defs);
  // One flip for the whole drawing: projected y increases north, SVG y down.
  const flip = el("g", { transform: "scale(1,-1)" });

  for (const s of DATA.states) {
    // Sparse by design: only the regions that need moving have an entry (AK
    // and HI in this bundle), and a bundle with no insets has no key at all.
    const place = DATA.meta.placement?.[s.usps];
    drawState(flip, defs, s, {
      transform: place
        ? `translate(${place.translate[0]},${place.translate[1]}) scale(${place.scale})`
        : null,
    });
  }
  svg.appendChild(flip);
  root.appendChild(svg);
}

let lastGridCols = 0;

const gridCols = () => {
  const avail = document.getElementById("chart").clientWidth ||
    cfg.GRID_MAX_COLS * cfg.GRID_MIN_CELL_PX;
  return Math.max(2, Math.min(cfg.GRID_MAX_COLS,
    Math.floor(avail / cfg.GRID_MIN_CELL_PX)));
};

function renderGrid(root, defs) {
  // Small multiples, most lopsided first. The national map is the poster; this
  // is the one that can actually be read state by state, which is the whole
  // reason it exists alongside it.
  const states = [...DATA.states].sort((a, b) => ringRatio(b) - ringRatio(a));
  // Columns are responsive, not fixed. The SVG scales to the container, so a
  // fixed 8 across renders each state at 44px under an 11px label on a phone --
  // not a small multiple so much as a rumour of one. Drop columns until each
  // cell clears GRID_MIN_CELL_PX on screen.
  const cols = lastGridCols = gridCols();
  const cell = cfg.GRID_CELL, pad = 7, labelH = 24;
  const rows = Math.ceil(states.length / cols);
  const svg = el("svg", {
    viewBox: `0 0 ${cols * cell} ${rows * (cell + labelH)}`,
    role: "img",
    "aria-label": cfg.ARIA_GRID,
  });
  svg.appendChild(defs);

  states.forEach((s, i) => {
    const cx = (i % cols) * cell, cy = Math.floor(i / cols) * (cell + labelH);
    const [bx0, by0, bx1, by1] = bboxOf(s);
    const k = Math.min((cell - 2 * pad) / (bx1 - bx0), (cell - 2 * pad) / (by1 - by0));
    // Fit, flip, and centre in the cell in one transform chain.
    const tx = cx + cell / 2 - ((bx0 + bx1) / 2) * k;
    const ty = cy + labelH + (cell - 2 * pad) / 2 + ((by0 + by1) / 2) * k;
    const g = el("g", { transform: `translate(${tx},${ty}) scale(${k},${-k})` });
    svg.appendChild(g);
    drawState(g, defs, s);

    // One label, not two. A separate ratio caption at the foot of the cell sits
    // closer to the next row's title than to its own state, and reads as
    // belonging to the wrong map.
    const label = el("text", {
      x: cx + cell / 2, y: cy + 17, "text-anchor": "middle",
      "font-size": 11, fill: cfg.INK, "font-weight": 600,
    });
    label.textContent = sub(cfg.GRID_LABEL,
      { region: s.usps, seats: s.seats, ratio: ringRatio(s).toFixed(0) });
    svg.appendChild(label);
  });
  root.appendChild(svg);
}

// ---------------------------------------------------------------------------
// Hover

const tooltip = document.getElementById("tooltip");
let hovered = null;

// Bound to pointerdown as well as pointermove. A touch device has no hover, and
// without the down binding every per-district number on this page -- population,
// area, density, ring width, fragment count -- is unreachable on a phone.
function onMove(evt) {
  const t = evt.target;
  if (!(t instanceof SVGElement) || t.tagName !== "use" || !t.dataset.k) {
    return clearHover();
  }
  if (hovered !== t) {
    if (hovered) hovered.setAttribute("fill", hovered.dataset.fill);
    hovered = t;
    t.dataset.fill = t.getAttribute("fill");
    t.setAttribute("fill", cfg.HIGHLIGHT);
  }
  const s = DATA.states.find((x) => x.usps === t.dataset.usps);
  const k = +t.dataset.k;
  const width = s.breaks[k] - s.breaks[k - 1];
  const pieces = s.district_pieces ? s.district_pieces[k - 1] : 1;

  const L = cfg.TOOLTIP_LABELS, U = cfg.AREA_UNIT;
  const row = (label, value) =>
    `<div class="t-row"><span>${label}</span><span>${value}</span></div>`;
  tooltip.innerHTML = `
    <div class="t-state">${sub(L.heading, { region: s.state, k, n: s.seats })}</div>
    ${row(L.population, fmt(s.district_pop[k - 1]))}
    ${row(L.area, `${fmt(s.district_area_km2[k - 1])} ${U}`)}
    ${row(L.density, `${fmt(s.district_density[k - 1], 1)}/${U}`)}
    ${row(L.width, `${(width * 100).toFixed(2)}${L.widthUnit}`)}
    ${k === 1 ? `<div class="t-note">${L.core}</div>` : ""}
    <div class="t-note">${pieces > 1
      ? sub(L.fragments, { n: fmt(pieces) })
      : L.onePiece}</div>`;

  const box = document.getElementById("figure").getBoundingClientRect();
  tooltip.style.opacity = "1";

  // Measure the tooltip rather than hard-coding its CSS width: the clamp has to
  // track #tooltip's max-width, and a magic number here goes silently wrong the
  // first time someone edits the stylesheet.
  const touch = evt.pointerType === "touch";
  const gap = touch ? 24 : 14;
  const x = evt.clientX - box.left, y = evt.clientY - box.top;
  tooltip.style.left = Math.max(0, Math.min(x + gap, box.width - tooltip.offsetWidth)) + "px";
  // On touch the finger covers the point it is reporting on, so sit above it.
  tooltip.style.top = Math.max(0, touch ? y - tooltip.offsetHeight - gap : y + gap) + "px";
}

function clearHover() {
  if (hovered) hovered.setAttribute("fill", hovered.dataset.fill);
  hovered = null;
  tooltip.style.opacity = "0";
}

// ---------------------------------------------------------------------------
// Legend. The colours carry no meaning of their own -- they cycle every five
// districts purely so neighbours stay tellable apart -- so the legend has to do
// two jobs. It explains the GEOMETRY: what a ring is, what its width means, and
// why some states are solid. And it says outright that the hues encode nothing,
// because a reader who sees five colours on a map will assume they do.

function nestedSwatch(widths, offset = 0) {
  // A schematic state: squares nested about a common centre, with the given
  // relative widths, drawn back to front exactly as the map is -- each with its
  // own paired stroke, since that pairing is what makes the scheme work.
  const size = 44, half = size / 2;
  let inner = "";
  let acc = 0;
  const total = widths.reduce((a, b) => a + b, 0);
  const edges = widths.map((w) => (acc += w) / total);
  for (let i = edges.length - 1; i >= 0; i--) {
    const d = (edges[i] * (size - 2));
    const slot = (i + offset) % cfg.FILLS.length;
    inner += `<rect x="${half - d / 2}" y="${half - d / 2}" width="${d}" height="${d}"
      fill="${cfg.FILLS[slot]}" stroke="${cfg.STROKES[slot]}" stroke-width="1" />`;
  }
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"
    aria-hidden="true">${inner}</svg>`;
}

function renderLegend() {
  document.getElementById("legend").innerHTML = cfg.LEGEND
    .map(({ widths, offset = 0, text }) =>
      `<div class="item">${nestedSwatch(widths, offset)}<span>${text}</span></div>`)
    .join("");
}

// ---------------------------------------------------------------------------
// Table view, so identity is never colour-alone

function renderTable() {
  const rows = [...DATA.states].sort((a, b) => ringRatio(b) - ringRatio(a)).map((s) => {
    const d = s.district_density.filter((x) => x > 0);
    return `<tr>
      <td>${s.state}</td><td>${s.seats}</td><td>${fmt(s.population)}</td>
      <td>${fmt(s.population / s.seats)}</td><td>${ringRatio(s).toFixed(1)}×</td>
      <td>${d.length ? fmt(Math.min(...d), 1) : "—"}</td>
      <td>${d.length ? fmt(Math.max(...d), 1) : "—"}</td>
      <td>${s.lobes.length}</td></tr>`;
  }).join("");
  document.getElementById("table").innerHTML = `
    <table class="districts">
      <thead><tr>${cfg.TABLE_HEADERS.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ---------------------------------------------------------------------------
// Preflight
//
// The bundle -- not config.js -- is the real contract for reusing this engine
// with other data, and it is written by hand or by a script the reuser owns.
// Every way of getting it slightly wrong used to fail badly: a missing meta key
// threw inside toLocaleString before anything rendered, a district_* array of
// the wrong length threw on the first hover, and an outline still in degrees
// drew the whole country as a dot with no error at all.
//
// So check the contract up front and say what is wrong in the reuser's terms.
// Errors block startup and are reported on the page; warnings fall back to
// something sane and go to the console under [data]. The full schema is in
// data/SCHEMA.md.

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const isPair = (v) => Array.isArray(v) && v.length >= 2 && isNum(v[0]) && isNum(v[1]);

function preflight(d) {
  const errs = [], warns = [];
  const MAX = 8;   // a badly wrong bundle should not print fifty near-identical lines

  if (!d || typeof d !== "object") return { errs: ["The bundle is not a JSON object."], warns };
  if (!d.meta || typeof d.meta !== "object") errs.push("meta: missing.");
  if (!Array.isArray(d.states) || !d.states.length) errs.push("states: missing or empty.");
  if (errs.length) return { errs, warns };

  const m = d.meta;
  if (!(Array.isArray(m.frame_bbox) && m.frame_bbox.length === 4 && m.frame_bbox.every(isNum))) {
    errs.push("meta.frame_bbox: expected [x0, y0, x1, y1] of finite numbers. The map view cannot be framed without it.");
  }
  for (const k of ["seats_total", "population_total", "contiguous_districts"]) {
    if (!isNum(m[k])) errs.push(`meta.${k}: expected a number, got ${JSON.stringify(m[k])}. It is shown in the stat strip.`);
  }

  const seen = new Set();
  for (const s of d.states) {
    const id = s?.usps ?? "(no usps)";
    const bad = (msg) => { if (errs.length < MAX) errs.push(`${id}: ${msg}`); };
    if (typeof s?.usps !== "string" || !s.usps) bad("usps: expected a non-empty string. It is the key that joins meta.placement and meta.color_offsets.");
    else if (seen.has(s.usps)) bad("usps: duplicated. Keys must be unique.");
    else seen.add(s.usps);
    if (typeof s?.state !== "string") bad("state: expected the display name as a string.");
    if (!Number.isInteger(s?.seats) || s.seats < 1) { bad("seats: expected an integer of 1 or more."); continue; }

    const b = s.breaks;
    if (!Array.isArray(b) || b.length !== s.seats + 1) {
      bad(`breaks: expected ${s.seats + 1} values for ${s.seats} seats, got ${Array.isArray(b) ? b.length : typeof b}.`);
    } else if (b[0] !== 0) {
      bad(`breaks[0]: expected 0 (the anchor), got ${b[0]}.`);
    } else if (b.some((v, i) => i && !(v > b[i - 1]))) {
      bad("breaks: expected strictly ascending scale factors.");
    } else if (Math.abs(b[b.length - 1] - 1) > 1e-6) {
      bad(`breaks: expected the last value to be 1 (the region's own outline), got ${b[b.length - 1]}.`);
    }

    for (const f of ["district_pop", "district_area_km2", "district_density"]) {
      if (!Array.isArray(s[f]) || s[f].length !== s.seats) {
        bad(`${f}: expected ${s.seats} values, got ${Array.isArray(s[f]) ? s[f].length : typeof s[f]}. The hover panel reads it per district.`);
      }
    }
    if (!isNum(s.population)) bad("population: expected a number. It is a table column.");
    if (!Array.isArray(s.lobes) || !s.lobes.length) { bad("lobes: missing or empty."); continue; }
    for (const [i, lobe] of s.lobes.entries()) {
      if (!isPair(lobe?.anchor)) bad(`lobes[${i}].anchor: expected [x, y], the fixed point every copy is scaled about.`);
      if (!Array.isArray(lobe?.outline) || lobe.outline.length < 3 || !lobe.outline.every(isPair)) {
        bad(`lobes[${i}].outline: expected 3 or more [x, y] pairs.`);
      }
    }
    if (!Array.isArray(s.district_pieces)) {
      warns.push(`${id}: district_pieces missing; the hover panel will call every district a single connected piece.`);
    }
  }

  // Coordinates left in degrees are the most likely porting mistake and the one
  // with no visible symptom beyond a very small map. Heuristic, so a warning
  // rather than an error: test the extent of the WHOLE bundle, since a single
  // point at the origin proves nothing. Any real projected extent that fits
  // inside lon/lat bounds would be a country 180 metres across.
  let ex0 = Infinity, ey0 = Infinity, ex1 = -Infinity, ey1 = -Infinity;
  for (const s of d.states) {
    for (const lobe of s.lobes ?? []) {
      for (const pt of lobe.outline ?? []) {
        if (!isPair(pt)) continue;
        if (pt[0] < ex0) ex0 = pt[0]; if (pt[0] > ex1) ex1 = pt[0];
        if (pt[1] < ey0) ey0 = pt[1]; if (pt[1] > ey1) ey1 = pt[1];
      }
    }
  }
  if (isNum(ex0) && ex0 >= -180 && ex1 <= 180 && ey0 >= -90 && ey1 <= 90) {
    warns.push("outline coordinates look like lon/lat degrees. The engine expects an equal-area projection in metres — see data/SCHEMA.md.");
  }
  // The baked offsets were greedy-coloured against a cycle of this length.
  // Change the palette length without re-running scripts/add_color_offsets.py
  // and neighbouring regions quietly stop being separated, which is the one
  // job the offsets exist to do.
  if (isNum(m.color_cycle) && m.color_cycle !== cfg.FILLS.length) {
    warns.push(`meta.color_cycle is ${m.color_cycle} but config.js has ${cfg.FILLS.length} fills. meta.color_offsets was computed for a ${m.color_cycle}-slot cycle and no longer keeps neighbours apart. Re-run scripts/add_color_offsets.py.`);
  }
  if (errs.length >= MAX) errs.push("(further problems not listed)");
  return { errs, warns };
}

// ---------------------------------------------------------------------------

function render() {
  // The grid label key is only true of the grid, so it comes and goes with it.
  document.getElementById("figure-note").textContent =
    view === "grid" ? cfg.GRID_NOTE : "";

  const root = document.getElementById("chart");
  root.textContent = "";
  clearHover();
  uid = 0;
  const defs = el("defs");
  (view === "map" ? renderMap : renderGrid)(root, defs);
  const svg = root.querySelector("svg");
  svg.addEventListener("pointermove", onMove);
  svg.addEventListener("pointerdown", onMove);
  svg.addEventListener("pointerleave", (e) => {
    // A touch pointer "leaves" the instant the finger lifts, which would flash
    // the tooltip open and shut on every tap. Touch clears on the next tap
    // instead: a tap off any district falls through onMove to clearHover, and a
    // tap outside the figure entirely is caught by the document listener below.
    if (e.pointerType !== "touch") clearHover();
  });
}

async function init() {
  document.getElementById("title").textContent = cfg.TITLE;
  document.title = cfg.TITLE;
  document.getElementById("subtitle").textContent = cfg.SUBTITLE;
  document.getElementById("explainer").textContent = cfg.EXPLAINER;
  document.getElementById("caveat").textContent = cfg.CAVEAT;
  document.getElementById("credit").innerHTML =
    `${cfg.DATA_CREDIT}${cfg.REPO_URL ? ` &middot; <a href="${cfg.REPO_URL}">${cfg.REPO_LABEL}</a>` : ""}`;

  const res = await fetch(cfg.DATA_FILE);
  if (!res.ok) throw new Error(`${cfg.DATA_FILE}: ${res.status}. Serve over HTTP, not file://`);
  DATA = await res.json();

  const { errs, warns } = preflight(DATA);
  for (const w of warns) console.warn("[data]", w);
  if (errs.length) {
    document.getElementById("chart").innerHTML =
      `<div class="dataerr"><strong>${cfg.DATA_FILE} does not match what the engine expects.</strong>
       <ul>${errs.map((e) => `<li>${e}</li>`).join("")}</ul>
       <p>The contract is documented in <code>data/SCHEMA.md</code>.</p></div>`;
    return;
  }

  const widest = [...DATA.states].sort((a, b) => ringRatio(b) - ringRatio(a))[0];
  const S = cfg.STAT_LABELS;
  document.getElementById("stats").innerHTML = [
    [fmt(DATA.meta.seats_total), S.units],
    [fmt(DATA.states.length), S.regions],
    [fmt(DATA.meta.population_total), S.population],
    [`${ringRatio(widest).toFixed(0)}×`, sub(S.widest, { region: widest.usps })],
    [fmt(DATA.meta.contiguous_districts), sub(S.contiguous, { total: DATA.meta.seats_total })],
  ].map(([n, k]) => `<div><span class="n">${n}</span><span class="k">${k}</span></div>`).join("");

  const viewSel = document.getElementById("view");
  // The two <option> labels live in config.js like every other string. The
  // values are the engine's, and must stay "map" and "grid".
  for (const o of viewSel.options) o.textContent = cfg.VIEW_LABELS[o.value] ?? o.value;
  viewSel.value = view;
  viewSel.addEventListener("change", (e) => { view = e.target.value; syncURL(); render(); });

  // Bound once, not per render: dismisses a tapped tooltip when the next tap
  // lands anywhere off the figure.
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest?.("#chart svg")) clearHover();
  });

  // The grid picks its column count from the container width, so a resize that
  // crosses a column boundary has to redraw. Debounced, and only when the count
  // actually changes -- redrawing 435 districts on every resize event would be
  // the most expensive thing this page does.
  let resizeTimer = null;
  addEventListener("resize", () => {
    if (view !== "grid") return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (gridCols() !== lastGridCols) render(); }, 150);
  });

  document.getElementById("ratio-note").textContent = cfg.RING_RATIO_NOTE;
  renderLegend();
  renderTable();
  render();
}

init().catch((err) => {
  document.getElementById("chart").innerHTML =
    `<p style="color:#b91c1c">${err.message}</p>`;
  console.error(err);
});
