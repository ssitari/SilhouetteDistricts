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
const fmt = (n, d = 0) => n.toLocaleString("en-US", { maximumFractionDigits: d });

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
    "aria-label": `${DATA.meta.seats_total} congressional districts drawn as nested state silhouettes`,
  });
  svg.appendChild(defs);
  // One flip for the whole drawing: projected y increases north, SVG y down.
  const flip = el("g", { transform: "scale(1,-1)" });

  for (const s of DATA.states) {
    const place = DATA.meta.placement[s.usps];
    drawState(flip, defs, s, {
      transform: place
        ? `translate(${place.translate[0]},${place.translate[1]}) scale(${place.scale})`
        : null,
    });
  }
  svg.appendChild(flip);
  root.appendChild(svg);
}

function renderGrid(root, defs) {
  // Small multiples, most lopsided first. The national map is the poster; this
  // is the one that can actually be read state by state, which is the whole
  // reason it exists alongside it.
  const states = [...DATA.states].sort((a, b) => ringRatio(b) - ringRatio(a));
  const cols = 8, cell = 160, pad = 7, labelH = 24;
  const rows = Math.ceil(states.length / cols);
  const svg = el("svg", {
    viewBox: `0 0 ${cols * cell} ${rows * (cell + labelH)}`,
    role: "img",
    "aria-label": "Every state's districts, small multiples, sorted by ring ratio",
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
    label.textContent = `${s.usps} · ${s.seats} · ${ringRatio(s).toFixed(0)}×`;
    svg.appendChild(label);
  });
  root.appendChild(svg);
}

// ---------------------------------------------------------------------------
// Hover

const tooltip = document.getElementById("tooltip");
let hovered = null;

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

  tooltip.innerHTML = `
    <div class="t-state">${s.state} &middot; district ${k} of ${s.seats}</div>
    <div class="t-row"><span>Population</span><span>${fmt(s.district_pop[k - 1])}</span></div>
    <div class="t-row"><span>Area</span><span>${fmt(s.district_area_km2[k - 1])} km²</span></div>
    <div class="t-row"><span>Density</span><span>${fmt(s.district_density[k - 1], 1)}/km²</span></div>
    <div class="t-row"><span>Ring width</span><span>${(width * 100).toFixed(2)}% of radius</span></div>
    ${k === 1 ? '<div class="t-note">The solid core.</div>' : ""}
    ${pieces > 1 ? `<div class="t-note">${fmt(pieces)} separate fragments.</div>` : '<div class="t-note">A single connected piece.</div>'}`;

  const box = document.getElementById("figure").getBoundingClientRect();
  tooltip.style.opacity = "1";
  tooltip.style.left = Math.min(evt.clientX - box.left + 14, box.width - 250) + "px";
  tooltip.style.top = (evt.clientY - box.top + 14) + "px";
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
  const items = [
    [nestedSwatch([1, 1, 1, 1]), "District 1 is the solid core. Higher numbers ring outward to the state border."],
    [nestedSwatch([5, 2, 1, 0.5]), "Rings crowd where people do. A thin ring is a dense one — every district holds the same number of people."],
    [nestedSwatch([1], 2), "A solid state elects a single representative: the district is the state."],
    [nestedSwatch([1, 1, 1, 1, 1, 1], 1), "The five colours mean nothing. They cycle so that neighbouring districts stay tellable apart, and each state starts at a different point in the cycle."],
  ];
  document.getElementById("legend").innerHTML = items
    .map(([svg, text]) => `<div class="item">${svg}<span>${text}</span></div>`)
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
      <thead><tr>
        <th>State</th><th>Seats</th><th>Population</th><th>Per district</th>
        <th>Ring ratio</th><th>Min density</th><th>Max density</th><th>Pieces</th>
      </tr></thead><tbody>${rows}</tbody>
    </table>`;
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
  svg.addEventListener("pointerleave", clearHover);
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

  const widest = [...DATA.states].sort((a, b) => ringRatio(b) - ringRatio(a))[0];
  document.getElementById("stats").innerHTML = [
    [fmt(DATA.meta.seats_total), "districts"],
    [fmt(DATA.states.length), "states"],
    // Resident population of the 50 states. Deliberately not the apportionment
    // population, which is larger because it adds overseas federal employees
    // and is the figure the seat counts were computed from.
    [fmt(DATA.meta.population_total), "residents, 50 states"],
    [`${ringRatio(widest).toFixed(0)}×`, `widest ring ratio (${widest.usps})`],
    [`${fmt(DATA.meta.contiguous_districts)}`, `of ${DATA.meta.seats_total} in one piece`],
  ].map(([n, k]) => `<div><span class="n">${n}</span><span class="k">${k}</span></div>`).join("");

  const viewSel = document.getElementById("view");
  viewSel.value = view;
  viewSel.addEventListener("change", (e) => { view = e.target.value; syncURL(); render(); });

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
