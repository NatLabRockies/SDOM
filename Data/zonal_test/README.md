# zonal_test fixture notes

This directory contains the canonical 2-area zonal fixture used by tests.
It is intended for model wiring/integration validation, not power-system realism.

## Hydro semantics (important)

- Global hydro formulation is `RunOfRiverFormulation` for both areas.
- Area A1 comes from a true run-of-river source folder.
- Area A2 reuses `lahy_hourly_2025` from the monthly-hydro-budget source.
- A2 monthly budget bounds (`lahy_max_hourly*` / `lahy_min_hourly*`) are
  deliberately not shipped in this fixture.

Implication: `LargeHydro@A2@` is acceptable for fixture testing but should not be
interpreted as a physically realistic run-of-river profile.
