// Engine for the four national district maps. Edit config.js, not this file.
//
// No D3, and no projection code, because neither is needed: the solvers emit
// coordinates already projected into equal-area metres, so drawing is a viewBox
// and a y-flip. That keeps the page dependency-free.
//
// Which model to draw comes from ?model= in the URL; every model is the same
// page with a different bundle and a different paragraph.
//
// THE ONE IDEA WORTH KNOWING
//
//   A district is never drawn as a band. Each is drawn as a SOLID shape, and
//   where those shapes nest, the larger ones are painted first and the smaller
//   ones land on top and hide their middles. What survives on screen is the
//   band -- with no boolean geometry and no ring construction.
//
//   Hit-testing falls out of the same trick. The topmost element under the
//   pointer is the smallest shape containing that point, which is exactly the
//   district the point belongs to. Re-filling that one element on hover
//   repaints only the band, because the inner shapes still cover the rest.
//
// TWO GEOMETRY FORMS
//
//   Both arrive as "a list of shapes per state, one per district, painted
//   largest first", and after that the code does not care which it got.
//
//   generated  the outward model. Every district IS the state outline scaled
//              about a fixed anchor, so the bundle ships one outline per lobe
//              plus a table of scale factors and the SVG transform does the
//              rest. 435 districts in 0.85 MB, one <path> reused by <use>.
//
//   explicit   inward, meridian, parallel. None of those is a scaled copy of
//              anything -- erosion is not a homothety, and a meridian leans
//              while a parallel bows -- so each district ships as real rings.
//              Inward's still nest (the solver's shells are cumulative), so
//              z-order carves them; the stripe models' slabs are disjoint and
//              paint order does not matter. See data/SCHEMA.md.

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

// Which model this page is showing. In the query string so the post can link
// straight at one of them.
const params = new URLSearchParams(location.search);
const modelKey = params.get("model") in cfg.MODELS ? params.get("model") : cfg.DEFAULT_MODEL;
const MODEL = cfg.MODELS[modelKey];

// ---------------------------------------------------------------------------
// Geometry helpers

// Scaling a shape about a fixed anchor is translate(a(1-s)) then scale(s) --
// the SVG transform does the arithmetic, so the outline ships once per lobe.
const scaleAbout = ([ax, ay], s) =>
  `translate(${((1 - s) * ax).toFixed(2)},${((1 - s) * ay).toFixed(2)}) scale(${s.toFixed(6)})`;

const ringPath = (ring) => {
  let d = "";
  for (let i = 0; i < ring.length; i++) {
    d += (i ? "L" : "M") + ring[i][0].toFixed(1) + "," + ring[i][1].toFixed(1);
  }
  return d + "Z";
};

// A district's shape is a flat list of rings; which are holes is left to
// fill-rule: evenodd, so the bundle never has to say. Michigan's outermost
// inward collar spans two lobes AND has a hole, and needs no special case.
const shapePath = (rings) => rings.map(ringPath).join("");

// Shoelace, for paint order only -- absolute value, largest ring wins.
const ringArea = (ring) => {
  let a = 0;
  for (let i = 0, n = ring.length; i < n; i++) {
    const [x0, y0] = ring[i], [x1, y1] = ring[(i + 1) % n];
    a += x0 * y1 - x1 * y0;
  }
  return Math.abs(a) / 2;
};
const shapeArea = (rings) => rings.reduce((m, r) => Math.max(m, ringArea(r)), 0);

const ringRatio = (state) => {
  const b = state.breaks;
  if (!Array.isArray(b)) return null;
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

const districtAttrs = (state, k) => ({
  fill: fillFor(state, k),
  // Every district carries its own stroke, which lands on its OUTER edge and
  // survives because whatever is drawn next is smaller. The fills alone sit
  // below the categorical-contrast floor by design, so these hairlines are what
  // actually separates one band from the next.
  stroke: strokeFor(state, k),
  "stroke-width": cfg.STROKE_WIDTH,
  // Harmless on a <use> (it cannot reach the shadow content, which takes it
  // from the referenced path instead) and required on a <path>.
  "vector-effect": "non-scaling-stroke",
  "data-usps": state.usps,
  "data-k": k,
});

// ---------------------------------------------------------------------------
// Drawing one state, either way

let uid = 0;

// Generated form: one <path> per lobe, reused by <use> at n scale factors.
function drawGenerated(g, defs, state) {
  state.lobes.forEach((lobe) => {
    const id = `o${uid++}`;
    // vector-effect goes HERE, on the referenced path, and not on the <use>
    // elements below -- it is a NON-inherited property, so setting it on a
    // <use> never reaches the shadow content that actually paints. Left there,
    // every district's stroke was scaled by its own transform AND by the
    // viewBox, which at national scale turned 0.75 user units into 0.75 METRES:
    // about two ten-thousandths of a pixel. The outward map had no visible
    // district borders at all, while fill and stroke COLOUR inherited normally
    // and made it look as though it did.
    defs.appendChild(el("path", {
      id, d: ringPath(lobe.outline), "vector-effect": "non-scaling-stroke",
    }));

    // Clip the whole lobe group rather than intersecting each band. On a
    // concave lobe a shrunk copy can cross its own boundary -- 6% of band area
    // in Michigan, which reads as districts spilling into Lake Huron -- and
    // clipping the group costs nothing while keeping the data as outline plus
    // scale factors.
    const cp = el("clipPath", { id: `c${id}`, clipPathUnits: "userSpaceOnUse" });
    cp.appendChild(el("use", { href: `#${id}` }));
    defs.appendChild(cp);

    const lg = el("g", { "clip-path": `url(#c${id})` });
    for (let k = state.seats; k >= 1; k--) {
      lg.appendChild(el("use", {
        href: `#${id}`,
        transform: scaleAbout(lobe.anchor, state.breaks[k]),
        ...districtAttrs(state, k),
      }));
    }
    g.appendChild(lg);

    // The lobe's own boundary, above the fills and OUTSIDE the clip. The
    // outermost district already strokes this line, but clipped -- a stroke
    // straddles its path, so clipping halves it. Redrawing it unclipped at full
    // weight keeps the silhouette, which is the whole conceit, crisp.
    g.appendChild(el("use", {
      href: `#${id}`, fill: "none", stroke: strokeFor(state, state.seats),
      "stroke-width": cfg.OUTLINE_WIDTH, "vector-effect": "non-scaling-stroke",
      "pointer-events": "none",
    }));
  });
}

// Explicit form: one <path> per district, painted largest first.
function drawExplicit(g, state) {
  // Sort by area rather than trusting the bundle's order. Nested shapes MUST go
  // largest first or the small ones vanish under the big ones; disjoint shapes
  // do not care. Deriving it from the geometry means neither model has to
  // declare a paint order, and neither can get it wrong.
  const order = state.shapes
    .map((rings, i) => ({ k: i + 1, rings, area: shapeArea(rings) }))
    .sort((a, b) => b.area - a.area);

  for (const { k, rings } of order) {
    if (!rings.length) continue;
    g.appendChild(el("path", {
      d: shapePath(rings), "fill-rule": "evenodd", ...districtAttrs(state, k),
    }));
  }

  // Where the shapes nest, the largest one IS the state outline, so it gets the
  // full-weight silhouette stroke on top -- matching what the generated form
  // does. Where they are disjoint slabs there is no such shape, and the state
  // border is already drawn by the slabs' own strokes.
  if (DATA.meta.shapes_nested && order.length) {
    g.appendChild(el("path", {
      d: shapePath(order[0].rings), "fill-rule": "evenodd", fill: "none",
      stroke: strokeFor(state, order[0].k),
      "stroke-width": cfg.OUTLINE_WIDTH, "vector-effect": "non-scaling-stroke",
      "pointer-events": "none",
    }));
  }
}

function drawState(parent, defs, state, transform) {
  const g = el("g", { class: "state", "data-usps": state.usps });
  if (transform) g.setAttribute("transform", transform);
  if (state.shapes) drawExplicit(g, state);
  else drawGenerated(g, defs, state);
  parent.appendChild(g);
}

// ---------------------------------------------------------------------------

function renderMap(root) {
  const [x0, y0, x1, y1] = DATA.meta.frame_bbox;
  const defs = el("defs");
  const svg = el("svg", {
    viewBox: `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`,
    role: "img",
    "aria-label": `${DATA.meta.seats_total} congressional districts, ${MODEL.title}`,
  });
  svg.appendChild(defs);
  // One flip for the whole drawing: projected y increases north, SVG y down.
  const flip = el("g", { transform: "scale(1,-1)" });

  for (const s of DATA.states) {
    // Sparse by design: only the regions that need moving have an entry (AK
    // and HI), and a bundle with no insets has no key at all.
    const place = DATA.meta.placement?.[s.usps];
    drawState(flip, defs, s,
      place ? `translate(${place.translate[0]},${place.translate[1]}) scale(${place.scale})` : null);
  }
  svg.appendChild(flip);
  root.appendChild(svg);
  return svg;
}

// ---------------------------------------------------------------------------
// Hover

const tooltip = document.getElementById("tooltip");
let hovered = null;

// Bound to pointerdown as well as pointermove. A touch device has no hover, and
// without the down binding every per-district number on this page -- population,
// area, density, fragment count -- is unreachable on a phone.
function onMove(evt) {
  const t = evt.target;
  if (!(t instanceof SVGElement) || !t.dataset.k) return clearHover();
  if (hovered !== t) {
    if (hovered) hovered.setAttribute("fill", hovered.dataset.fill);
    hovered = t;
    t.dataset.fill = t.getAttribute("fill");
    t.setAttribute("fill", cfg.HIGHLIGHT);
  }
  const s = DATA.states.find((x) => x.usps === t.dataset.usps);
  const k = +t.dataset.k;
  const pieces = s.district_pieces ? s.district_pieces[k - 1] : 1;
  const L = cfg.TOOLTIP_LABELS, U = cfg.AREA_UNIT;
  const row = (label, value) =>
    `<div class="t-row"><span>${label}</span><span>${value}</span></div>`;

  // Ring width is a scale factor, so it exists only where the geometry is
  // generated from one. The other three models have no equivalent.
  const width = s.breaks ? s.breaks[k] - s.breaks[k - 1] : null;

  tooltip.innerHTML = `
    <div class="t-state">${sub(L.heading, { region: s.state, k, n: s.seats })}</div>
    ${row(L.population, fmt(s.district_pop[k - 1]))}
    ${row(L.area, `${fmt(s.district_area_km2[k - 1])} ${U}`)}
    ${row(L.density, `${fmt(s.district_density[k - 1], 1)}/${U}`)}
    ${width === null ? "" : row(L.width, `${(width * 100).toFixed(2)}${L.widthUnit}`)}
    ${width !== null && k === 1 ? `<div class="t-note">${L.core}</div>` : ""}
    <div class="t-note">${pieces > 1
      ? sub(L.fragments, { n: fmt(pieces) })
      : L.onePiece}</div>`;

  const box = document.getElementById("figure").getBoundingClientRect();
  tooltip.style.opacity = "1";
  // Measure the tooltip rather than hard-coding its CSS width: the clamp has to
  // track #tooltip's max-width, and a magic number goes silently wrong the
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
// Legend
//
// The colours carry no meaning of their own -- they cycle every five districts
// purely so neighbours stay tellable apart -- so the legend has two jobs. It
// explains the GEOMETRY: what a band is and what its width means. And it says
// outright that the hues encode nothing, because a reader who sees five colours
// on a map will assume they do.

const SWATCH = 44;

function nestedSwatch(widths, offset) {
  // A schematic state: squares nested about a common centre, drawn back to
  // front exactly as the map is -- each with its own paired stroke, since that
  // pairing is what makes the scheme work.
  const half = SWATCH / 2;
  const total = widths.reduce((a, b) => a + b, 0);
  let acc = 0;
  const edges = widths.map((w) => (acc += w) / total);
  let inner = "";
  for (let i = edges.length - 1; i >= 0; i--) {
    const d = edges[i] * (SWATCH - 2);
    const slot = (i + offset) % cfg.FILLS.length;
    inner += `<rect x="${half - d / 2}" y="${half - d / 2}" width="${d}" height="${d}"
      fill="${cfg.FILLS[slot]}" stroke="${cfg.STROKES[slot]}" stroke-width="1" />`;
  }
  return inner;
}

function stripeSwatch(widths, offset, dir) {
  // The same schematic for a state cut into slabs. Vertical stripes are
  // numbered from the right, because district 1 is the easternmost slice.
  const total = widths.reduce((a, b) => a + b, 0);
  const span = SWATCH - 2;
  let acc = 1, inner = "";
  for (let i = 0; i < widths.length; i++) {
    const w = (widths[i] / total) * span;
    const slot = (i + offset) % cfg.FILLS.length;
    // i = 0 is district 1, and it starts at the far end either way: the east
    // edge for a meridian cut, the south edge for a parallel one. Both are the
    // high-coordinate side in SVG, since y already points down here.
    const pos = SWATCH - 1 - acc - w;
    const box = dir === "v"
      ? `x="${pos}" y="1" width="${w}" height="${span}"`
      : `x="1" y="${pos}" width="${span}" height="${w}"`;
    inner += `<rect ${box} fill="${cfg.FILLS[slot]}"
      stroke="${cfg.STROKES[slot]}" stroke-width="1" />`;
    acc += w;
  }
  return inner;
}

function renderLegend() {
  document.getElementById("legend").innerHTML = MODEL.legend
    .map(({ kind, widths, offset = 0, dir = "v", text }) => {
      const inner = kind === "stripes"
        ? stripeSwatch(widths, offset, dir)
        : nestedSwatch(widths, offset);
      return `<div class="item"><svg width="${SWATCH}" height="${SWATCH}"
        viewBox="0 0 ${SWATCH} ${SWATCH}" aria-hidden="true">${inner}</svg>
        <span>${text}</span></div>`;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// Table view, so identity is never colour-alone

function renderTable() {
  const rows = [...DATA.states]
    .sort((a, b) => b.seats - a.seats || a.state.localeCompare(b.state))
    .map((s) => {
      const d = s.district_density.filter((x) => x > 0);
      const whole = (s.district_pieces || []).filter((p) => p === 1).length;
      return `<tr>
        <td>${s.state}</td><td>${s.seats}</td><td>${fmt(s.population)}</td>
        <td>${fmt(s.population / s.seats)}</td>
        <td>${d.length ? fmt(Math.min(...d), 1) : "—"}</td>
        <td>${d.length ? fmt(Math.max(...d), 1) : "—"}</td>
        <td>${whole} of ${s.seats}</td></tr>`;
    }).join("");
  document.getElementById("table").innerHTML = `
    <table class="districts">
      <thead><tr>${cfg.TABLE_HEADERS.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ---------------------------------------------------------------------------
// Stat strip

function statValue(key) {
  const m = DATA.meta;
  switch (key) {
    case "units": return [fmt(m.seats_total), cfg.STAT_LABELS.units];
    case "regions": return [fmt(DATA.states.length), cfg.STAT_LABELS.regions];
    case "population": return [fmt(m.population_total), cfg.STAT_LABELS.population];
    case "contiguous":
      return [fmt(m.contiguous_districts),
        sub(cfg.STAT_LABELS.contiguous, { total: m.seats_total })];
    case "maxPieces": {
      let worst = 0, who = "";
      for (const s of DATA.states) {
        for (const p of s.district_pieces || []) {
          if (p > worst) { worst = p; who = s.usps; }
        }
      }
      return [fmt(worst), sub(cfg.STAT_LABELS.maxPieces, { region: who })];
    }
    case "ringRatio": {
      const rated = DATA.states.filter((s) => ringRatio(s) !== null);
      if (!rated.length) return null;
      const w = rated.sort((a, b) => ringRatio(b) - ringRatio(a))[0];
      return [`${ringRatio(w).toFixed(0)}×`,
        sub(cfg.STAT_LABELS.ringRatio, { region: w.usps })];
    }
    default: return null;
  }
}

function renderStats() {
  document.getElementById("stats").innerHTML = MODEL.stats
    .map(statValue).filter(Boolean)
    .map(([n, k]) => `<div><span class="n">${n}</span><span class="k">${k}</span></div>`)
    .join("");
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
// something sane and go to the console under [data]. Full schema: data/SCHEMA.md.

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
    errs.push("meta.frame_bbox: expected [x0, y0, x1, y1] of finite numbers. The map cannot be framed without it.");
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

    // Exactly one of the two geometry forms.
    const gen = "breaks" in s || "lobes" in s, exp = "shapes" in s;
    if (gen && exp) bad("carries both `shapes` and `breaks`/`lobes`. A state uses one geometry form or the other, not both.");
    else if (!gen && !exp) bad("no geometry: expected either `shapes` (explicit rings) or `lobes` + `breaks` (generated).");
    else if (exp) {
      if (!Array.isArray(s.shapes) || s.shapes.length !== s.seats) {
        bad(`shapes: expected ${s.seats} entries for ${s.seats} seats, got ${Array.isArray(s.shapes) ? s.shapes.length : typeof s.shapes}.`);
      } else {
        s.shapes.forEach((rings, i) => {
          if (!Array.isArray(rings) || !rings.length) return bad(`shapes[${i}]: expected at least one ring.`);
          for (const r of rings) {
            if (!Array.isArray(r) || r.length < 3 || !r.every(isPair)) {
              return bad(`shapes[${i}]: every ring needs 3 or more [x, y] pairs.`);
            }
          }
        });
      }
    } else {
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
      if (!Array.isArray(s.lobes) || !s.lobes.length) bad("lobes: missing or empty.");
      else for (const [i, lobe] of s.lobes.entries()) {
        if (!isPair(lobe?.anchor)) bad(`lobes[${i}].anchor: expected [x, y], the fixed point every copy is scaled about.`);
        if (!Array.isArray(lobe?.outline) || lobe.outline.length < 3 || !lobe.outline.every(isPair)) {
          bad(`lobes[${i}].outline: expected 3 or more [x, y] pairs.`);
        }
      }
    }

    for (const f of ["district_pop", "district_area_km2", "district_density"]) {
      if (!Array.isArray(s[f]) || s[f].length !== s.seats) {
        bad(`${f}: expected ${s.seats} values, got ${Array.isArray(s[f]) ? s[f].length : typeof s[f]}. The hover panel reads it per district.`);
      }
    }
    if (!isNum(s.population)) bad("population: expected a number. It is a table column.");
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
  const eat = (pt) => {
    if (!isPair(pt)) return;
    if (pt[0] < ex0) ex0 = pt[0]; if (pt[0] > ex1) ex1 = pt[0];
    if (pt[1] < ey0) ey0 = pt[1]; if (pt[1] > ey1) ey1 = pt[1];
  };
  for (const s of d.states) {
    for (const lobe of s.lobes ?? []) for (const pt of lobe.outline ?? []) eat(pt);
    for (const rings of s.shapes ?? []) for (const r of rings) for (const pt of r) eat(pt);
  }
  if (isNum(ex0) && ex0 >= -180 && ex1 <= 180 && ey0 >= -90 && ey1 <= 90) {
    warns.push("coordinates look like lon/lat degrees. The engine expects an equal-area projection in metres — see data/SCHEMA.md.");
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

function renderNav() {
  document.getElementById("nav").innerHTML = Object.entries(cfg.MODELS)
    .map(([key, m]) => key === modelKey
      ? `<span class="here" aria-current="page">${m.title.split(" — ")[0]}</span>`
      : `<a href="?model=${key}">${m.title.split(" — ")[0]}</a>`)
    .join("") + `<a class="aside" href="illinois.html">Illinois</a>`;
}

async function init() {
  document.getElementById("title").textContent = MODEL.title;
  document.title = `${MODEL.title} · ${cfg.SITE_TITLE}`;
  document.getElementById("blurb").textContent = MODEL.blurb;
  document.getElementById("note").textContent = MODEL.note;
  document.getElementById("credit").innerHTML =
    `${cfg.DATA_CREDIT}${cfg.REPO_URL ? ` &middot; <a href="${cfg.REPO_URL}">${cfg.REPO_LABEL}</a>` : ""}`;
  renderNav();

  const res = await fetch(MODEL.data);
  if (!res.ok) throw new Error(`${MODEL.data}: ${res.status}. Serve over HTTP, not file://`);
  DATA = await res.json();

  const { errs, warns } = preflight(DATA);
  for (const w of warns) console.warn("[data]", w);
  if (errs.length) {
    document.getElementById("chart").innerHTML =
      `<div class="dataerr"><strong>${MODEL.data} does not match what the engine expects.</strong>
       <ul>${errs.map((e) => `<li>${e}</li>`).join("")}</ul>
       <p>The contract is documented in <code>data/SCHEMA.md</code>.</p></div>`;
    return;
  }

  renderStats();
  renderLegend();
  renderTable();

  const root = document.getElementById("chart");
  root.textContent = "";
  const svg = renderMap(root);
  svg.addEventListener("pointermove", onMove);
  svg.addEventListener("pointerdown", onMove);
  svg.addEventListener("pointerleave", (e) => {
    // A touch pointer "leaves" the instant the finger lifts, which would flash
    // the tooltip open and shut on every tap. Touch clears on the next tap
    // instead: a tap off any district falls through onMove to clearHover, and a
    // tap outside the figure entirely is caught by the document listener below.
    if (e.pointerType !== "touch") clearHover();
  });
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest?.("#chart svg")) clearHover();
  });
}

init().catch((err) => {
  document.getElementById("chart").innerHTML =
    `<div class="dataerr">${err.message}</div>`;
  console.error(err);
});
