---
name: infrasys-data-modeling
description: "Design memory-efficient Python data models with NatLabRockies Infrasys. Use when choosing Component fields, SupplementalAttribute associations, time-series storage, identifiers, indexes, or lookup patterns for modeling systems."
argument-hint: "Describe the domain entities, data sizes, relationships, time-varying fields, and common lookups."
---

# Infrasys Data Modeling

Design component and supplemental-attribute schemas for Infrasys-backed modeling systems, with explicit attention to memory use, retrieval paths, and data lifecycle.

## Procedure

1. **Confirm the environment and API.** Read the project's dependency constraint and inspect the installed Infrasys version and public API before proposing implementation. Prefer the project's pinned version over assumptions from `main`; check local examples, tests, and subclass conventions. Infrasys APIs and internal indexes can change between releases.
2. **Write down access patterns.** Identify the required lookups (for example, UUID, type plus name, owner plus attribute kind, or owner plus time-series name and features), expected query frequency, result cardinality, update frequency, and whether queries need scans, ranges, or exact matches.
3. **Classify each datum by meaning and lifecycle.** Use the decision table below. Keep static identity and core domain properties with their component; represent related optional/shared concepts separately; keep temporal arrays in Infrasys time-series storage; keep derived values out of the canonical model unless they are costly and frequently reused.
4. **Choose keys and relationships.** Use stable identifiers for identity and Infrasys public relationship APIs. Make ownership and multiplicity explicit. Do not assume names are globally unique or create parallel object registries until the installed API and actual lookup workload justify them.
5. **Choose representations for size and sparsity.** Estimate payload bytes and Python-object overhead. Prefer compact numeric arrays for dense homogeneous values, sparse encodings for mostly absent values, and ordinary objects for small, heterogeneous domain records. Avoid Python lists of boxed numbers for large numeric data.
6. **Map hot queries to direct retrieval.** Use the narrowest public Infrasys lookup (type/name or UUID for components; owner, name, type, and features for time series). Use listing/filter APIs for discovery or occasional scans, not as a substitute for an index in a hot repeated query.
7. **Implement a minimal slice and measure.** Add representative components and attributes, exercise expected retrieval and serialization, and profile memory and lookup time at realistic scale before adding caches or custom indexes.
8. **Validate lifecycle and consistency.** Test duplicates, missing/ambiguous lookup keys, shared associations, updates/removals, serialization/deserialization, and time-series reads. Any app-owned secondary index must be maintained atomically on add, update, and remove.

## Representation Decision Table

| Data | Infrasys representation | Use when |
|---|---|---|
| Independently addressable domain entity with stable identity and core, mostly static properties | `Component` fields | The object has its own lifecycle, participates in domain relationships, or must be fetched as a typed entity. |
| Optional, orthogonal, or reusable structured data associated with one or more components | `SupplementalAttribute` | The concept is not intrinsic to the component schema, may be shared, or should be attached/detached independently. Keep the association explicit through `System` APIs. |
| Numeric values indexed by time, scenarios, or other series metadata | `TimeSeriesData` attached to a component or supplemental attribute | Values are temporal arrays, potentially large, and should be retrieved as full series or slices rather than as ordinary component fields. |
| Small scalar used for filtering/identity of a series | Time-series `name` or compact JSON-serializable feature metadata | It distinguishes a series at lookup time. Keep features descriptive and small; do not put arrays or bulky domain payloads in metadata. |
| Large source files, bulky derived tables, or data with a lifecycle outside the system object graph | External file/object store plus a small stable reference in the model | The payload should not be copied into every component or serialized into metadata. Define ownership, path portability, and cleanup explicitly. |

## Infrasys API and Source-Grounded Guidance

- Build on `System` and its public methods: `add_components`, `get_component`, `get_component_by_uuid`, `get_components`, supplemental-attribute methods, and time-series methods. Do not mutate private manager dictionaries or SQLite tables directly.
- `System.get_components(type, filter_func=...)` is useful for typed enumeration and filtering. Treat filtering as a scan over candidates unless the installed implementation proves otherwise; narrow by type first and avoid repeating broad scans in hot loops.
- Model supplemental data as an explicit `SupplementalAttribute` and attach/retrieve it using the system's association APIs. A supplemental attribute can be associated with components, so avoid making a separate copy per owner when the same immutable concept can be shared.
- Add a time series with a stable semantic `name` and only the features needed to disambiguate it. For retrieval, use the owner and identifying metadata; use `list_time_series_metadata` or `list_time_series_keys` to discover matches, then retrieve by key when appropriate. Include the series type when names/features alone are not unique.
- Infrasys separates time-series metadata/associations from time-series array storage. The documented default is Arrow-backed storage; in-memory storage trades memory for access behavior. Select the backend from measured workload and data size. Set `time_series_directory` deliberately when default temporary storage is too small or unsuitable, such as on compute nodes. Use read-only mode for immutable loaded data when supported by the installed version.
- Avoid keeping both a full time-series array and a duplicate Python-list or per-timestep object representation in component fields. If a cache is necessary, define its size bound, invalidation rule, and authority relationship to Infrasys storage.
- Treat feature metadata as lookup metadata, not as a flexible dumping ground. Keep it JSON-serializable, normalized, and low-volume; encode stable dimensions such as scenario, forecast, or stage only when they are needed to select a series.

## Data-Structure Trade-offs

- **Hash maps (`dict`)**: average-case $O(1)$ exact-key lookup and insertion, with memory overhead per entry and occasional resizing. Use for frequently accessed identifier-to-object maps when Infrasys does not already provide the lookup. Hash operations can degrade in pathological collision cases, so do not promise strict worst-case constant time.
- **Sets**: average-case $O(1)$ membership with no associated payload. Use for uniqueness/membership checks, not ordered data or key-to-value retrieval.
- **Lists/tuples**: compact relative to maps for small ordered collections and good for iteration; membership or predicate search is $O(n)$. Use for small child collections or ordered sequences, not repeated lookup by an identifier.
- **Dense numeric arrays**: contiguous typed storage avoids the per-number object overhead of Python lists and supports vectorized operations. Use NumPy/Arrow-compatible arrays for large homogeneous numeric payloads and time series.
- **Sparse representations**: store only nonzero/present entries when occupancy is low enough to offset index overhead. Use dense arrays when most positions are populated or dense arithmetic dominates; benchmark the crossover for the actual dtype and access pattern.
- **Secondary indexes**: map a queried key to an object or compact position when repeated scans are too slow. They consume memory and require synchronized writes/deletes. Add only for a measured hot path, and prefer built-in Infrasys lookup APIs where they satisfy the query.
- **Object graphs**: references avoid copying shared objects but add pointer/object overhead and can make serialization or traversal more complex. Prefer explicit IDs or shared immutable supplemental attributes when that makes ownership and persistence clearer.

For rough memory estimates, count payload bytes plus index and Python-object overhead; do not estimate a dictionary-backed model as only the sum of numeric values. Validate estimates with `sys.getsizeof` for shallow size and a recursive/profiling tool for retained size, since `getsizeof` does not include referenced objects.

## Retrieval Design Checklist

- Can a caller identify a component with the public API and a stable identifier without scanning every object?
- Are lookup keys unambiguous within the relevant component type or series owner?
- Is a proposed filter an occasional discovery operation or a repeated hot-path query?
- Does each supplemental attribute need one owner or many, and are shared instances safe for the intended mutation semantics?
- Can a time-series read request a slice instead of materializing the complete horizon?
- Does a custom index point to canonical Infrasys objects rather than duplicate payloads?
- Are add/update/remove and deserialization paths covered so custom indexes cannot become stale?
- Have representative memory and latency measurements been made at expected scale?

## Deliverables

When applying this skill, return:

1. A concise entity/field classification, including component versus supplemental attribute versus time series.
2. The proposed identity, relationship, and lookup keys, with expected scan/index behavior.
3. A memory/storage recommendation tied to approximate sizes, sparsity, and workload.
4. Any assumptions, version-specific API details, risks, and focused tests or measurements needed to validate the design.

## References

- [Infrasys component manager](https://github.com/NatLabRockies/infrasys/blob/main/src/infrasys/component_manager.py)
- [Infrasys supplemental attribute manager](https://github.com/NatLabRockies/infrasys/blob/main/src/infrasys/supplemental_attribute_manager.py)
- [Infrasys time-series manager](https://github.com/NatLabRockies/infrasys/blob/main/src/infrasys/time_series_manager.py)
- [Infrasys time-series metadata store](https://github.com/NatLabRockies/infrasys/blob/main/src/infrasys/time_series_metadata_store.py)
- [Component concepts](https://github.com/NatLabRockies/infrasys/blob/main/docs/explanation/components.md)
- [Time-series concepts and storage options](https://github.com/NatLabRockies/infrasys/blob/main/docs/explanation/time_series.md)