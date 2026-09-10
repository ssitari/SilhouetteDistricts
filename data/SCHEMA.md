# The bundle contract

`app.js` draws whatever bundle `?model=` points it at. Nothing in it is specific
to the United States, to Congress, or to population — it takes a set of
**regions**, each divided into **units**, and paints them. If you want to use
this engine for something else, this file is the thing to satisfy. The scripts in
`scripts/` are one way of producing a bundle, for one dataset; they are not the
only way.

A region's geometry arrives in one of two forms, and a bundle may use either.
Both reach the renderer as the same thing — a list of shapes, one per unit,
painted largest first — so nothing downstream cares which it got.

| Form | Fields | Use it when |
|---|---|---|
| **generated** | `lobes` + `breaks` | every unit is the region's outline scaled about a fixed anchor. One outline plus *n* numbers draws *n* units: 435 districts in 0.85 MB. |
| **explicit** | `shapes` | anything else. Each unit ships its own rings. |

The generated form is a large saving and a narrow one — it only works if the
units really are homothetic copies. Erosion isn't, and neither is a straight cut
across a projected map, so three of this repo's four models use `shapes`.

`app.js` checks this contract on load. Anything it can't work with is reported on
the page, by field, instead of throwing.

---

## Vocabulary

The field names below are fixed, and they are US-shaped for historical reasons.
Read them generically:

| Field name | Means |
|---|---|
| `state` | the **region** — the outer shape, whatever it is |
| `usps` | the region's **short unique key** — need not be two letters |
| `seats` | how many **units** this region is divided into |
| `district_*` | per-**unit** arrays |

Nothing on screen has to use these words. Every visible label lives in
`config.js`; see the *Vocabulary* section there.

---

## Top level

```jsonc
{
  "meta":   { ... },
  "states": [ { ... }, ... ]     // one entry per region, at least one
}
```

## `meta`

| Key | Type | Required | Notes |
|---|---|---|---|
| `frame_bbox` | `[x0, y0, x1, y1]` | **yes** | The map view's viewBox, in projected units. Without it the map cannot be framed. |
| `seats_total` | number | **yes** | Total units. Stat strip and the map's aria-label. |
| `population_total` | number | **yes** | Stat strip. |
| `contiguous_districts` | number | **yes** | Stat strip. |
| `placement` | `{key: {scale, translate: [x, y]}}` | no | Per-region transform for the map view — this is where Alaska and Hawaii get moved and shrunk. A region with no entry is drawn where the projection puts it. |
| `color_offsets` | `{key: int}` | no | Which slot in the colour cycle each region starts at. Missing keys fall back to `CYCLE_FALLBACK_OFFSET`. |
| `color_cycle` | int | no | The cycle length `color_offsets` was computed for. If it disagrees with `FILLS.length` in `config.js`, the page warns: the offsets have silently stopped separating neighbours. |
| `shapes_nested` | bool | no | Only meaningful for the explicit form. See `shapes` below. |

Anything else in `meta` is ignored by the page. The current bundle also carries
`generated`, `sources`, `conus_crs`, `conus_bbox` and `simplify_tolerance_m`,
which exist for provenance, not for drawing.

## `states[]`

| Key | Type | Required | Notes |
|---|---|---|---|
| `usps` | string | **yes** | Unique. Joins `placement` and `color_offsets`. |
| `state` | string | **yes** | Display name, used in the hover panel and the table. |
| `seats` | int ≥ 1 | **yes** | Number of units. |
| `population` | number | **yes** | Table column. |
| `breaks` | number[] | **yes** | Length `seats + 1`. See below. |
| `lobes` | object[] | **yes** | At least one. See below. |
| `district_pop` | number[] | **yes** | Length `seats`. Hover panel. |
| `district_area_km2` | number[] | **yes** | Length `seats`. Hover panel; unit label is `AREA_UNIT` in `config.js`. |
| `district_density` | number[] | **yes** | Length `seats`. Hover panel and two table columns. |
| `district_pieces` | int[] | no | Length `seats`. How many disconnected fragments each unit is. Absent, every unit is described as a single piece. |

Then **exactly one** of the two geometry forms:

| Key | Type | Form | Notes |
|---|---|---|---|
| `breaks` + `lobes` | see below | generated | Both, or neither. |
| `shapes` | array | explicit | Length `seats`. See below. |

Carrying both is an error, and so is carrying neither; the page says so by name.

`qa`, `crs` and `ideal_per_district` are carried for provenance and not read.

### `breaks`

The heart of it. `breaks[k]` is the scale factor at which a copy of the region's
outline, scaled about the lobe anchor, has exactly the outer edge of unit *k*.

- length `seats + 1`
- `breaks[0] === 0` — the anchor itself
- strictly ascending
- `breaks[seats] === 1` — the region's own outline

Unit *k* is drawn as a **solid** copy scaled by `breaks[k]`, painted before unit
*k−1*, which lands on top and hides its middle. What survives on screen is the
annulus between `breaks[k−1]` and `breaks[k]`. No ring is ever constructed.

### `lobes[]`

A region drawn as one or more disjoint pieces — a mainland and its islands. Each
is scaled about its own anchor.

| Key | Type | Notes |
|---|---|---|
| `anchor` | `[x, y]` | The fixed point every scaled copy is anchored to. |
| `outline` | `[[x, y], ...]` | 3 or more points. The ring is closed for you; don't repeat the first point. |

`area_share` is carried by the current bundle and not read by the page.

### `shapes` — the explicit form

`shapes[k-1]` is unit *k*, as a flat list of rings:

```jsonc
"shapes": [
  [ [[x,y], ...], [[x,y], ...] ],   // unit 1: an outer ring and a hole
  [ [[x,y], ...] ],                 // unit 2: one ring
  ...
]
```

**Which rings are holes is not recorded.** Every ring of a unit goes into one
`<path>` drawn with `fill-rule: evenodd`, which resolves containment on its own.
A unit that is both multi-part and holed — Michigan's outermost inward collar
spans two lobes *and* has a hole — needs no special case.

Rings are closed for you; don't repeat the first point.

**Paint order is derived, not declared.** The renderer sorts a region's shapes
by area and paints the largest first, so a bundle cannot get it wrong. That
supports both kinds of `shapes` with one code path:

- **Nested** shapes, where `shapes[k]` sits inside `shapes[k-1]`, need exactly
  that order: the larger is painted first and the smaller lands on top and hides
  its middle, so what survives on screen is the band between them. This is how
  the inward model works — the solver's `shells` are cumulative erosions, so
  successive differences *are* the districts, and no band is ever constructed.
- **Disjoint** shapes, like the meridian and parallel slabs, don't overlap, so
  paint order is irrelevant and sorting is harmless.

Set `meta.shapes_nested` if they nest. The renderer uses it for one thing: a
nested region's largest shape is its outline, so it gets the full-weight
silhouette stroke. Disjoint slabs already draw the region border between them.

---

## Coordinates

**Project first.** `app.js` contains no projection code — `outline` and `anchor`
are drawn as-is into the SVG viewBox, with a single global y-flip because
projected y increases north and SVG y increases down.

So the coordinates must be:

- in an **equal-area** projection (this bundle uses per-region Albers/UTM, see
  each state's `crs`), because equal population per equal ring area is the whole
  claim the picture makes;
- in **metres**, or at least in units consistent across all regions and with
  `meta.frame_bbox` and `meta.placement`;
- **y increasing north**.

Leaving coordinates as lon/lat degrees is the most likely porting mistake and
the one with no visible symptom beyond a very small map, so the page warns about
it explicitly.

## Size

Outlines are the entire payload — 881 KB of the current 849 KB bundle is
`outline` arrays (they compress). Simplify before bundling. This one uses a
500 m tolerance, and `pathData()` rounds to a decimetre on the way out.

---

## Minimal example

Two regions, three units each, no insets, no colour offsets:

```json
{
  "meta": {
    "frame_bbox": [0, 0, 1000000, 1000000],
    "seats_total": 6,
    "population_total": 600000,
    "contiguous_districts": 6
  },
  "states": [
    {
      "usps": "A", "state": "Region A", "seats": 3, "population": 300000,
      "breaks": [0, 0.5, 0.8, 1],
      "district_pop":       [100000, 100000, 100000],
      "district_area_km2":  [62500, 97500, 90000],
      "district_density":   [1.6, 1.03, 1.11],
      "district_pieces":    [1, 1, 1],
      "lobes": [{
        "anchor": [250000, 250000],
        "outline": [[0, 0], [500000, 0], [500000, 500000], [0, 500000]]
      }]
    },
    {
      "usps": "B", "state": "Region B", "seats": 3, "population": 300000,
      "breaks": [0, 0.4, 0.7, 1],
      "district_pop":       [100000, 100000, 100000],
      "district_area_km2":  [40000, 82500, 127500],
      "district_density":   [2.5, 1.21, 0.78],
      "district_pieces":    [1, 1, 1],
      "lobes": [{
        "anchor": [750000, 250000],
        "outline": [[500000, 0], [1000000, 0], [1000000, 500000], [500000, 500000]]
      }]
    }
  ]
}
```
