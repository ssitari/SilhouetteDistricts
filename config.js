// The only file to edit when re-situating these maps. app.js is the engine.
//
// Two things this file cannot cover, so that the rule above stays honest:
//   - index.html and map.html carry the <title> and link-preview meta tags.
//     Crawlers do not run this module, so those have to be static.
//   - the data bundles are the real contract. What the engine requires of them
//     is written down in data/SCHEMA.md; app.js checks it on load and reports
//     what is missing on the page rather than throwing.

export const SITE_TITLE = "Four ways to cut a country";

export const SITE_BLURB =
  "Four non-partisan rules for dividing every state into equal-population " +
  "congressional districts, run over the same 2020 census blocks with the same " +
  "checks — and what the 2020 presidential vote does under each of them.";

// Shown under the chooser on the front page. The honest framing, once, rather
// than repeated on all five pages.
export const SITE_CAVEAT =
  "Geometric thought experiments, not redistricting proposals. Every district " +
  "holds the same share of its state to within a fraction of a percent. None of " +
  "them knows where anyone lives beyond a census block, and none of them is " +
  "trying to be fair to anything except arithmetic.";

// ---------------------------------------------------------------------------
// Palette. The same five-colour symbology as the figures in docs/, so the pages
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
// the state adjacency graph (scripts/add_color_offsets.py, baked into every
// bundle as meta.color_offsets). Starting everyone at slot 0 made one hue
// dominate -- district 1 the same colour in all fifty states, and the six
// single-district states entirely that colour, fusing Montana, Wyoming and the
// Dakotas into one tan mass with their shared borders invisible.
//
// Changing the LENGTH of the palette invalidates those baked offsets. The page
// warns when it no longer matches meta.color_cycle; re-run add_color_offsets.py.
export const CYCLE_FALLBACK_OFFSET = 0;

// Interior district boundaries are hairlines: on a state like New Jersey the
// outer bands are well under 1% of the width, and a full-weight stroke on each
// would be most of what is left of the band. The state's own outline is drawn
// at full weight so the silhouette stays crisp.
export const STROKE_WIDTH = 0.75;
export const OUTLINE_WIDTH = 1;

export const SURFACE = "#ffffff";
export const INK = "#1a1a1a";
export const INK_MUTED = "#6b7280";
export const HIGHLIGHT = "#c2410c";

// ---------------------------------------------------------------------------
// Vocabulary
//
// Everything below is a label. The bundle's FIELD names are fixed -- `state`,
// `seats`, `usps`, `district_pop` and the rest, all set out in data/SCHEMA.md --
// but nothing on screen has to use those words.
//
// {braces} are substituted by app.js. Only the placeholders named in each
// comment exist; an unknown one is left on screen verbatim, which is the
// failure you want -- visible, not silent.

export const LOCALE = "en-US";   // number and thousands-separator formatting
export const AREA_UNIT = "km²";  // must match the units in district_area_km2

// The stat strip. Which of these a page shows is set per model, below.
export const STAT_LABELS = {
  units: "districts",
  regions: "states",
  // Resident population of the 50 states. Deliberately not the apportionment
  // population, which is larger because it adds overseas federal employees and
  // is the figure the seat counts were computed from.
  population: "residents, 50 states",
  contiguous: "of {total} in one piece",
  maxPieces: "worst district, in pieces ({region})",
  ringRatio: "widest ring ratio ({region})",
};

// The hover/tap panel. {region} is the state name, {k} the district number,
// {n} the state's seat count in the heading and the fragment count in
// `fragments`.
export const TOOLTIP_LABELS = {
  heading: "{region} · district {k} of {n}",
  population: "Population",
  area: "Area",
  density: "Density",
  // Shown only by the outward model, the one whose bands are defined by a
  // scale factor and so have a width that means something.
  width: "Ring width",
  widthUnit: "% of radius",
  core: "The solid core.",
  onePiece: "A single connected piece.",
  fragments: "{n} separate fragments.",
};

// Table columns. The ORDER is fixed -- app.js computes the cells positionally --
// so rename freely but do not reorder or add.
export const TABLE_HEADERS = [
  "State", "Seats", "Population", "Per district",
  "Min density", "Max density", "Districts in one piece",
];

export const DATA_CREDIT =
  "2020 Census P.L. 94-171 Redistricting Data (block level); " +
  "Census cartographic boundaries (cb_2020_us_state_500k, cb_2023_us_cd118_500k); " +
  "2020 Apportionment Results, Table 1; VEST 2020 Illinois precinct returns. " +
  "Census sources public domain.";

export const REPO_URL = "https://github.com/ssitari/SilhouetteDistricts";
export const REPO_LABEL = "Source and method on GitHub";

// ---------------------------------------------------------------------------
// The four models
//
// `blurb` is the whole of what each page says about itself. The argument lives
// in the post; this is the two or three sentences a reader needs if they landed
// here from a link and have not read it.
//
// `stats` names which entries from STAT_LABELS that page's strip shows, in
// order. ringRatio needs `breaks`, so only the outward model can offer it.
//
// `legend` swatches: kind "nested" draws squares inside one another with the
// given relative band widths, innermost first; kind "stripes" draws parallel
// bands, vertical or horizontal. `offset` starts a swatch at a different slot
// in the colour cycle.

export const MODELS = {
  outward: {
    title: "Outward — nested silhouettes",
    tagline: "Every district is the shape of its own state.",
    data: "data/districts.json",
    blurb:
      "District 1 is a solid scaled copy of the state, centred on an interior " +
      "anchor; the rest are rings around it, each a larger copy of the same " +
      "outline. Ring width is inverse population density — where a ring is thin, " +
      "people are packed. Because a state's centre is rarely where its people " +
      "live, the outer rings collapse into filaments around the cities on the edge.",
    note:
      "The prettiest and the least practical: only 115 of the 435 are a single " +
      "connected piece. A ring around a concave state severs wherever a district " +
      "further in crosses it, so Florida's worst district is 100 separate " +
      "fragments and Texas's is 97.",
    stats: ["units", "regions", "population", "ringRatio", "contiguous"],
    legend: [
      { kind: "nested", widths: [1, 1, 1, 1],
        text: "District 1 is the solid core. Higher numbers ring outward to the state border." },
      { kind: "nested", widths: [5, 2, 1, 0.5],
        text: "Rings crowd where people do. A thin ring is a dense one — every district holds the same number of people." },
      { kind: "nested", widths: [1], offset: 2,
        text: "A solid state elects a single representative: the district is the state." },
      { kind: "nested", widths: [1, 1, 1, 1, 1, 1], offset: 1,
        text: "The five colours mean nothing. They cycle so neighbouring districts stay tellable apart, and each state starts at a different point in the cycle." },
    ],
  },

  inward: {
    title: "Inward — erosion from the border",
    tagline: "Districts peel off the state line, one collar at a time.",
    data: "data/inward.json",
    blurb:
      "Every census block is ranked by its distance to the state line; sort, " +
      "accumulate, cut. District 1 is the outermost collar and the last district " +
      "is whatever core survives. There is no anchor at all, so the centroid " +
      "problem that drives the outward model simply disappears.",
    note:
      "The most practical of the four: 344 of 435 districts are a single " +
      "connected piece, and no district is more than 10. It costs the silhouette, " +
      "though — offsetting strips an equal margin from every side, so the shorter " +
      "dimension burns off faster and a state flattens as it goes in.",
    stats: ["units", "regions", "population", "contiguous", "maxPieces"],
    legend: [
      { kind: "nested", widths: [1, 1, 1, 1],
        text: "District 1 is the outer collar. Higher numbers work inward to whatever core is left." },
      { kind: "nested", widths: [0.5, 1, 2, 5],
        text: "A thin collar is a dense one — every district holds the same number of people." },
      { kind: "nested", widths: [1], offset: 2,
        text: "A solid state elects a single representative: the district is the state." },
      { kind: "nested", widths: [1, 1, 1, 1, 1, 1], offset: 1,
        text: "The five colours mean nothing. They cycle so neighbouring districts stay tellable apart, and each state starts at a different point in the cycle." },
    ],
  },

  meridian: {
    title: "Meridian — cut north to south",
    tagline: "Vertical slices, numbered east to west.",
    data: "data/meridian.json",
    blurb:
      "Sort every block by longitude, accumulate, cut. No anchor and no erosion: " +
      "half-planes are disjoint and exhaustive, so the districts partition the " +
      "state by construction. District 1 is the easternmost slice.",
    note:
      "The most even of the four — worst population deviation 0.189%. The cuts " +
      "are true meridians, and Albers is a conic projection, so they come out " +
      "straight but tilted, fanning by about 15% of a state's width. They are not " +
      "curved; they lean.",
    stats: ["units", "regions", "population", "contiguous", "maxPieces"],
    legend: [
      { kind: "stripes", dir: "v", widths: [1, 1, 1, 1],
        text: "District 1 is the easternmost slice. Higher numbers run west." },
      { kind: "stripes", dir: "v", widths: [0.5, 1, 2, 4],
        text: "A narrow slice is a dense one — every district holds the same number of people." },
      { kind: "stripes", dir: "v", widths: [1], offset: 2,
        text: "A solid state elects a single representative: the district is the state." },
      { kind: "stripes", dir: "v", widths: [1, 1, 1, 1, 1, 1], offset: 1,
        text: "The five colours mean nothing. They cycle so neighbouring districts stay tellable apart, and each state starts at a different point in the cycle." },
    ],
  },

  parallel: {
    title: "Parallel — cut east to west",
    tagline: "Horizontal bands, numbered south to north.",
    data: "data/parallel.json",
    blurb:
      "The same idea as the meridian model turned ninety degrees: sort every " +
      "block by latitude, accumulate, cut. District 1 is the southernmost band.",
    note:
      "A parallel is an arc in Albers, not a line, so these cuts genuinely do " +
      "curve — gently, about 1.7 km of bow across Illinois. Polygons are " +
      "segmentized at 0.02° before reprojection so the arcs survive; joining four " +
      "slab corners alone would replace them with chords.",
    stats: ["units", "regions", "population", "contiguous", "maxPieces"],
    legend: [
      { kind: "stripes", dir: "h", widths: [1, 1, 1, 1],
        text: "District 1 is the southernmost band. Higher numbers run north." },
      { kind: "stripes", dir: "h", widths: [0.5, 1, 2, 4],
        text: "A narrow band is a dense one — every district holds the same number of people." },
      { kind: "stripes", dir: "h", widths: [1], offset: 2,
        text: "A solid state elects a single representative: the district is the state." },
      { kind: "stripes", dir: "h", widths: [1, 1, 1, 1, 1, 1], offset: 1,
        text: "The five colours mean nothing. They cycle so neighbouring districts stay tellable apart, and each state starts at a different point in the cycle." },
    ],
  },
};

export const DEFAULT_MODEL = "outward";

// ---------------------------------------------------------------------------
// The Illinois page
//
// A different question, so a different page: not what the districts look like
// but where a real electorate lands inside them.

export const ILLINOIS = {
  title: "Illinois — where the votes land",
  tagline: "The 2020 presidential vote, redistributed under all four models.",
  data: "data/illinois.json",
  blurb:
    "Each model's Illinois districts, filled by the two-party Democratic share " +
    "of the 2020 presidential vote — real ballots, redistributed. The enacted " +
    "118th-Congress map is the fifth column, for scale.",
  note:
    "This is not a prediction. Nobody ran in these districts, turnout would " +
    "differ, and candidates matter. It is what redistricting analysts call a " +
    "partisan index: the same votes, counted inside different lines.",
  // Diverging ramp, Democratic share of the two-party vote. Deliberately not
  // the district palette -- here the colour DOES carry the measurement, so it
  // must not be confused with the five hues that carry nothing.
  RAMP: ["#b2182b", "#ef8a62", "#fddbc7", "#f7f7f7", "#d1e5f0", "#67a9cf", "#2166ac"],
  DOMAIN: [0.25, 0.875],   // clamps of the ramp, in Democratic two-party share
  MIDPOINT: 0.5,
  RAMP_LABEL: "Democratic share of the two-party presidential vote, 2020",
  CHART_LABEL:
    "Every district under every model, on one axis. Each dot is one of " +
    "Illinois's 17 seats; the vertical rule is an even 50–50 split.",
};
