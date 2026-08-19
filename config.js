// The only file to edit when re-situating this map. app.js is the engine.

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

// Alternating fills. A sequential ramp turns a 52-ring state into a smooth
// gradient in which no single district can be picked out; two alternating tones
// keep every boundary legible down to sub-1% ring widths, which is exactly where
// the crowding worth seeing happens.
// Validated: CVD separation dE 54.3, normal-vision dE 55.4 -- both far clear of
// the floor, which is what this pair has to do. The validator's lightness-band
// and chroma checks are categorical-palette rules and fail here by design; a
// deliberately maximum-contrast alternation is not a categorical palette.
export const TWO_TONE = ["#12384f", "#ccd9e2"];

// The pale tone sits at 1.4:1 against a white page, so a state whose outermost
// ring lands on it would lose its own silhouette against the background. Every
// lobe therefore carries a hairline of its own boundary. This is the relief the
// contrast warning obliges, alongside the table view.
export const OUTLINE = "#94a3b8";

// Sequential ramp for the density view: one hue, light to dark. Six steps, not
// eight -- adjacent steps in a sequential ramp are necessarily close, so fewer
// and wider-spaced steps stay tellable apart on bands only a pixel or two wide.
export const DENSITY_RAMP = [
  "#e4eef6", "#b3d0e4", "#7fabcb", "#5286af", "#2b6291", "#0f375a",
];

export const SURFACE = "#ffffff";
export const INK = "#1a1a1a";
export const INK_MUTED = "#6b7280";
export const HIGHLIGHT = "#c2410c";

export const DEFAULT_VIEW = "map";      // "map" | "grid"
export const DEFAULT_COLOR = "alternating";  // "alternating" | "density"

export const DATA_CREDIT =
  "2020 Census P.L. 94-171 Redistricting Data (block level); " +
  "Census cartographic boundaries (cb_2020_us_state_500k); " +
  "2020 Apportionment Results, Table 1. All public domain.";

export const REPO_URL = "https://github.com/ssitari/SilhouetteDistricts";
export const REPO_LABEL = "Source and method on GitHub";
