// The only file to edit when re-situating this map. app.js is the engine.
//
// Two things this file cannot cover, so that the rule above stays honest:
//   - index.html carries the <title> and the link-preview meta tags. Crawlers
//     do not run this module, so those have to be static. Edit them there.
//   - data/districts.json is the real contract. What the engine requires of it
//     is written down in data/SCHEMA.md; app.js checks it on load and reports
//     what is missing on the page rather than throwing.

export const TITLE = "Congressional districts as nested silhouettes";

export const SUBTITLE =
  "Every district is the shape of its own state, scaled about a fixed centre and " +
  "carrying an equal share of the 2020 population. District 1 is the solid core; " +
  "the rest are rings around it.";

// The sentence that says what a reader is actually looking at. Drawn in the
// figure, not in a chrome bar.
export const EXPLAINER =
  "Ring width is inverse population density. Where a ring is thin, people are " +
  "packed; where it is thick, they are sparse. Because a state's centre is " +
  "rarely where its people live, the outer rings collapse into filaments around " +
  "the cities on the edge.";

export const CAVEAT =
  "A geometric thought experiment, not a redistricting proposal. Every district " +
  "holds the same share of its state to within a fraction of a percent — and only " +
  "115 of the 435 are a single connected piece. A ring around a concave state " +
  "severs wherever a district further in crosses it, so Florida's worst district " +
  "is 100 separate fragments and Texas's is 97.";

export const DATA_FILE = "data/districts.json";

// ---------------------------------------------------------------------------
// Palette. The same five-colour symbology as the figures in docs/, so the page
// and the printed maps agree.
//
// The cycle repeats every five districts and carries NO meaning -- it only
// keeps neighbours apart. Because it is cyclic, only ADJACENT separation
// matters (district k against k+1; district 1 and district 9 never touch),
// which makes the hue order a real decision: tan -> green -> blue -> yellow ->
// cyan roughly doubles the worst adjacent pair over the order as originally
// supplied (fills dE 3.3 -> 6.3, strokes 8.2 -> 14.4).
//
// The pairing is the point. The fills sit below the dE 15 categorical floor and
// are NOT asked to separate anything -- they carry mass. The darker strokes,
// all clearing 3:1 against the surface, carry the boundaries. So every district
// is drawn WITH its own stroke; dropping the strokes to save a paint would
// leave five pale tints that genuinely cannot be told apart.
export const FILLS = ["#f3d9b8", "#c5e3d0", "#c9d6ee", "#f7e6b0", "#c9e4e8"];
export const STROKES = ["#8c5c14", "#1d6b46", "#20447e", "#8a7213", "#2f6d78"];

// Each state also STARTS at a different slot in the cycle, greedy-coloured over
// the state adjacency graph (scripts/add_color_offsets.py, baked into the
// bundle as meta.color_offsets). Starting everyone at slot 0 made one hue
// dominate -- district 1 the same colour in all fifty states, and the six
// single-district states entirely that colour, fusing Montana, Wyoming and the
// Dakotas into one tan mass with their shared borders invisible.
export const CYCLE_FALLBACK_OFFSET = 0;

// Interior district boundaries are hairlines: on a state like New Jersey the
// outer rings are well under 1% of the radius, and a full-weight stroke on each
// would be most of what is left of the ring. The state's own outline is drawn
// at full weight so the silhouette -- the whole conceit -- stays crisp.
export const STROKE_WIDTH = 0.75;
export const OUTLINE_WIDTH = 1;

export const SURFACE = "#ffffff";
export const INK = "#1a1a1a";
export const INK_MUTED = "#6b7280";
export const HIGHLIGHT = "#c2410c";

// "Ring ratio" carries three jobs on this page -- a headline stat, the third
// number in every grid label, and a table column -- and is the one term a
// reader cannot infer from context. Defined next to the stat strip, where it
// first appears.
export const RING_RATIO_NOTE =
  "Ring ratio is a state's widest ring divided by its narrowest — how unevenly " +
  "its people are spread across it. New York's widest ring is 90 times its " +
  "narrowest; Iowa's is 3.";

// The grid cells are labelled with a bare triple that means nothing on its own.
export const GRID_NOTE =
  "Each cell is labelled state · seats · ring ratio, most lopsided first.";

export const DEFAULT_VIEW = "map";      // "map" | "grid"

export const DATA_CREDIT =
  "2020 Census P.L. 94-171 Redistricting Data (block level); " +
  "Census cartographic boundaries (cb_2020_us_state_500k); " +
  "2020 Apportionment Results, Table 1. All public domain.";

export const REPO_URL = "https://github.com/ssitari/SilhouetteDistricts";
export const REPO_LABEL = "Source and method on GitHub";


// ---------------------------------------------------------------------------
// Vocabulary
//
// Everything below is a label. The bundle's FIELD names are fixed -- `state`,
// `seats`, `usps`, `district_pop` and the rest, all set out in data/SCHEMA.md --
// but nothing on screen has to use those words. This is the section that makes
// the page talk about ridings in provinces, or wards in councils, instead of
// districts in states.
//
// {braces} are substituted by app.js. Only the placeholders named in each
// comment exist; an unknown one is left on screen verbatim, which is the
// failure you want -- visible, not silent.

export const LOCALE = "en-US";   // number and thousands-separator formatting
export const AREA_UNIT = "km²";  // must match the units in district_area_km2

// The <select> that swaps views, and what a screen reader is told each view is.
export const VIEW_LABELS = {
  map: "National map",
  grid: "All states, sorted by lopsidedness",
};
export const ARIA_MAP = "{units} congressional districts drawn as nested state silhouettes";  // {units}
export const ARIA_GRID = "Every state's districts, small multiples, sorted by ring ratio";

// The stat strip across the top. {region} is the leader's short code, {total}
// the unit count.
export const STAT_LABELS = {
  units: "districts",
  regions: "states",
  // Resident population of the 50 states. Deliberately not the apportionment
  // population, which is larger because it adds overseas federal employees and
  // is the figure the seat counts were computed from.
  population: "residents, 50 states",
  widest: "widest ring ratio ({region})",
  contiguous: "of {total} in one piece",
};

// The hover/tap panel. {region} is the state name, {k} the district number,
// {n} the state's seat count in the heading and the fragment count in
// `fragments`.
export const TOOLTIP_LABELS = {
  heading: "{region} · district {k} of {n}",
  population: "Population",
  area: "Area",
  density: "Density",
  width: "Ring width",
  widthUnit: "% of radius",
  core: "The solid core.",
  onePiece: "A single connected piece.",
  fragments: "{n} separate fragments.",
};

// Grid cell captions: {region} · {seats} · {ratio}.
export const GRID_LABEL = "{region} · {seats} · {ratio}×";

// Table columns. The ORDER is fixed -- app.js computes the cells positionally --
// so rename freely but do not reorder or add.
export const TABLE_HEADERS = [
  "State", "Seats", "Population", "Per district",
  "Ring ratio", "Min density", "Max density", "Pieces",
];

// Legend. `widths` is the relative width of each band in the schematic swatch,
// innermost first; `offset` starts that swatch at a different slot in the
// colour cycle. Rewrite the sentences for new data: "A solid state elects a
// single representative" is simply false about anything that is not a US state.
export const LEGEND = [
  { widths: [1, 1, 1, 1],
    text: "District 1 is the solid core. Higher numbers ring outward to the state border." },
  { widths: [5, 2, 1, 0.5],
    text: "Rings crowd where people do. A thin ring is a dense one — every district holds the same number of people." },
  { widths: [1], offset: 2,
    text: "A solid state elects a single representative: the district is the state." },
  { widths: [1, 1, 1, 1, 1, 1], offset: 1,
    text: "The five colours mean nothing. They cycle so that neighbouring districts stay tellable apart, and each state starts at a different point in the cycle." },
];

// ---------------------------------------------------------------------------
// Small-multiples grid
//
// 50 states sit comfortably 8 across. A different number of regions wants a
// different figure. MIN_CELL_PX is the responsive floor: app.js drops columns
// until each cell is at least this wide on screen, because 8 columns inside a
// 350px phone renders each state at 44px under an 11px label, which is not a
// small multiple so much as a rumour of one.
export const GRID_MAX_COLS = 8;
export const GRID_MIN_CELL_PX = 92;
export const GRID_CELL = 160;   // internal drawing units, not screen pixels
