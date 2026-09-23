---
name: python-large-scale-map-creation
description: "Use when: creating, extending, reviewing, or optimizing Python geographic maps, interactive network maps, Plotly maps, or large-scale spatial visualizations. Covers scalable data preparation, bounded-trace rendering, geographic fallback behavior, visual encodings, and render validation."
argument-hint: "Describe the map users need, data volume, geographic inputs, renderer, required interactivity, output format, and performance constraints"
user-invocable: false
---

# Python Large-Scale Map Creation

Create correct, useful, and responsive Python geographic maps when the input may contain thousands
of nodes, lines, regions, or observations. This workflow is repository-agnostic: follow the host
project's data model, plotting library, test framework, and output conventions.

## Outcome

- A map with a defined data contract, geographic behavior, and visual hierarchy.
- Rendering work that stays bounded as network size grows.
- Interactive information that remains available without creating one renderer object per feature.
- Focused tests for data, scale-sensitive rendering, and meaningful failure modes.

## Use When

- Building or modifying an interactive geographic or network map in Python.
- Rendering large point, line, polygon, transmission, road, route, or asset datasets.
- Diagnosing blank, slow, memory-heavy, or unreadable map outputs.
- Reviewing a map implementation for scalability and visual correctness.

## Inputs To Establish

Before implementation, determine:

1. The expected maximum counts of points, segments, polygons, and categorical groups.
2. Coordinate reference system, longitude/latitude column names, valid ranges, and missing-data
   policy.
3. Required interactions: hover fields, legend filtering, selection, pan/zoom, and static export.
4. Output contract: returned figure object, HTML/image artifact, overwrite policy, and artifact
   metadata if the host project tracks it.
5. Whether a basemap or external tile service is permitted in the deployment environment.

If the volume is unknown, instrument a representative dataset and record feature counts before
choosing rendering granularity.

## Constraints

- Keep source traversal, tabular transformation, and rendering in separate functions or modules.
- Define stable plotting-ready schemas before creating renderer objects.
- Do not create one trace, layer, or artist per line segment at large scale.
- Use vectorized NumPy/pandas/GeoPandas operations for numeric transforms and classification when
  memory use remains reasonable.
- Preserve deterministic output: stable ordering, explicit category ordering, and reproducible
  fallback coordinates when fallbacks are enabled.
- Make optional rendering parameters keyword-only for new public APIs when consistent with the
  host project's API conventions.

## Workflow

### 1. Define the Map Contract

1. State the audience question the map must answer and rank layers by importance.
2. Specify each plotting table's columns, units, types, nullability, and coordinate convention.
3. Define how invalid, missing, duplicated, and out-of-range coordinates are handled.
4. Decide whether missing coordinates are excluded, replaced with deterministic fallback positions,
   or treated as a validation error. Never silently fabricate positions.
5. Choose a narrow test or representative render that can expose a blank map, wrong bounds, or
   trace explosion.

### 2. Build a Plotting-Ready Data Boundary

1. Extract domain data into normalized tables or arrays with explicit schemas.
2. Apply area, scenario, time, or result-set filters during extraction rather than after renderer
   objects have been created.
3. Validate selector ambiguity early. When more than one result set could apply, require an explicit
   selection and report available choices.
4. Aggregate missing-coordinate counts and issue one actionable warning per collection operation.
5. Keep domain objects and renderer-specific types out of this data boundary so the rendering layer
   can be tested from compact fixtures.

Example schema separation:

```python
nodes = pd.DataFrame({"id": ids, "lon": lon, "lat": lat, "capacity_mw": capacity})
edges = pd.DataFrame({"id": edge_ids, "lon_a": lon_a, "lat_a": lat_a, "lon_b": lon_b, "lat_b": lat_b})
```

### 3. Compute Geographic Extent Deliberately

1. Combine coordinates from every visible layer when computing bounds.
2. Add proportional padding and a small absolute minimum so single-location maps remain visible.
3. Use a documented fallback extent only when the map has no valid coordinates; warn the caller.
4. Derive initial zoom from the larger longitude/latitude span using tested thresholds or the
   renderer's supported fit-to-bounds operation.
5. Preserve antimeridian and projected-coordinate concerns explicitly when the dataset can cross
   those boundaries; do not assume all coordinates are local longitude/latitude values.

### 4. Design Bounded Rendering

1. Add layers from background to foreground: regions or boundaries, edges, nodes, highlighted
   assets, then annotations.
2. Group features into a bounded number of traces or layers by meaningful visual classes such as
   voltage band, technology, status, or width bucket.
3. For many line segments, concatenate each batch as coordinate sequences separated by the
   renderer's segment-break marker (for example, `None` in Plotly). Render one trace per batch,
   not one per segment.
4. Quantize continuous line widths into a small fixed bucket count. Choose the bucket count based on
   visual distinction and verify that it does not scale with feature count.
5. Use grouped point traces for categories. For extremely dense points, evaluate clustering,
   aggregation, WebGL, vector tiles, or a static-density layer according to the renderer's limits.
6. Keep trace count approximately proportional to visual classes and buckets, not to source rows.

Plotly-style batched line pattern:

```python
for bucket in width_buckets:
    batch = edges.loc[edges["width_bucket"] == bucket]
    lon = np.column_stack((batch["lon_a"], batch["lon_b"], np.nan)).ravel()
    lat = np.column_stack((batch["lat_a"], batch["lat_b"], np.nan)).ravel()
    fig.add_trace(go.Scattermap(lon=lon, lat=lat, mode="lines", line={"width": bucket}))
```

Adapt the break marker and trace type to the selected library. Keep per-feature metadata in compact
structured custom data when the renderer supports it; do not duplicate large strings across traces.

### 5. Use Perceptually Useful Encodings

1. Reserve color for categorical meaning and choose a stable, documented color map.
2. Scale capacity-like marker areas with a bounded log or square-root transform; convert to the
   renderer's expected size units when it expects marker area rather than radius.
3. Scale widths with bounded square-root or log transforms when values span orders of magnitude.
4. Use opacity and draw order to distinguish available, selected, and emphasized layers without
   obscuring geographic context.
5. Provide a visibility halo or contrasting underlay only when necessary to preserve important thin
   lines over a busy basemap.
6. Make legends concise, ordered, and interactive. Use legend groups so a user can toggle related
   layers together.

### 6. Make Interactions Informative

1. Define hover content before rendering and include only decision-useful fields with units.
2. Store scalar metadata in indexed custom-data columns or equivalent structured payloads.
3. Keep hover templates fixed per trace class; avoid generating one text payload per feature when
   structured fields can produce the same result.
4. Ensure zero-row categories, empty result sets, and absent optional layers still yield a usable
   figure and a truthful legend state.

### 7. Test Scale and Failure Behavior

1. Start with a failing focused test for the requested behavior when feasible.
2. Test data extraction separately from rendering with small deterministic fixtures.
3. Verify trace or layer count stays bounded for a synthetic large network. Assert a limit derived
   from number of visual groups and buckets, not number of edges.
4. Verify hover/custom-data alignment after batching so each segment retains correct metadata.
5. Cover empty data, all-missing coordinates, partially missing coordinates, zero or equal scaling
   values, unknown categories, and ambiguous selectors.
6. Run a smoke render that writes the required artifact and asserts expected layers and layout
   configuration. Use image or HTML snapshots only when they are stable in the host project.
7. Run the narrowest lint, type, and test commands provided by the host project.

## Decision Guide

| Condition | Default action |
| --- | --- |
| Fewer than a few hundred features and no interactive lag | Use clear category-based traces; still avoid per-feature traces unless each needs unique styling. |
| Thousands of homogeneous or width-scaled edges | Batch segments by a fixed number of style buckets. |
| Hundreds of thousands of points or edges | Benchmark representative data; use aggregation, clustering, WebGL, vector tiles, or a specialized renderer. |
| Multiple possible scenarios or runs | Require a selector; do not pick one arbitrarily. |
| Some coordinates are missing | Exclude and aggregate warnings, or use documented deterministic fallback only when spatial approximation is acceptable. |
| No valid coordinates remain | Render a defined empty state or fallback extent with a warning; do not crash from min/max calculations. |
| A feature has no assigned style | Apply a visible default and issue a warning naming the unstyled class. |
| Static offline HTML is required | Avoid required online basemaps; use a compatible local/static base or disclose the dependency. |

## Performance Checks

- Record representative source-row counts and final trace/layer counts.
- Confirm the number of traces remains bounded as edge count increases.
- Vectorize scaling, bucket assignment, and coordinate assembly rather than loop over rows.
- Avoid repeated DataFrame concatenation, repeated layout updates, and per-feature renderer calls in
  hot paths.
- Keep generated artifact size practical; for interactive HTML, avoid embedding duplicated library
  bundles when a project-approved external bundle or shared asset is available.
- Profile render time and browser responsiveness with production-like data before declaring the map
  large-scale ready.

## Completion Criteria

- Plotting-ready schemas and coordinate policy are explicit.
- Map bounds work for normal, single-location, and no-coordinate inputs.
- Rendering uses bounded batches for high-cardinality lines and points.
- Visual scales are bounded and perceptually appropriate.
- Hover information and legends remain accurate after batching.
- Tests cover normal, empty, missing-coordinate, ambiguous-selection, and scale-sensitive cases.
- A focused rendering or artifact-generation check passes with representative data.

## Return Summary Format

```markdown
## Map Implementation Summary

### Delivered

[Map behavior and output]

### Scale Design

- Source features: [representative counts]
- Rendered traces/layers: [bounded count and grouping strategy]
- Data and rendering separation: [modules or functions]

### Geographic Behavior

- Coordinate validation and fallback policy: [policy]
- Initial extent and zoom: [policy]

### Validation

- [Focused tests/checks run]
- [Large-data or trace-count evidence]

### Notes

[Basemap dependency, known constraints, or follow-up benchmark]
```