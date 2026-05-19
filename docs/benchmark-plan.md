# SDOM Benchmarking Plan (main vs PR branch)

## Goal

Create a repeatable benchmark workflow to compare runtime between:

- `main`
- feature/PR branch

for key SDOM workflows (IO, model build, solve, results, export, resiliency).

The plan is intentionally two-tiered:

1. **Tier A: low-noise Python/runtime benchmarks** (stable signal)
2. **Tier B: end-to-end solve benchmarks** (realistic signal, higher variance)

---

## Scope and principles

- Keep first version small, deterministic, and easy to run locally.
- Use the same machine and environment for branch comparisons.
- Record benchmark artifacts (`.json`) for historical comparison.
- Separate **PR-safe quick suite** from **nightly/deeper suite**.
- Do not block PRs on noisy tests until baselines are established.

---

## Tooling choice

Use `pytest-benchmark`.

Why:
- integrates with existing pytest workflow,
- easy `--benchmark-json` output,
- built-in compare support,
- simple CI integration.

### Add dependency

Use project’s preferred dependency workflow to add:

- `pytest-benchmark`

---

## Proposed benchmark layout

```text
tests/
  benchmarks/
    conftest.py
    test_bench_io.py
    test_bench_model_build.py
    test_bench_solver.py
    test_bench_results_export.py
    test_bench_resiliency.py
scripts/
  bench_compare.py
benchmark-results/
  (json artifacts, optional local folder)
docs/
  benchmark-plan.md
```

---

## Benchmark cases to include

## Tier A — low-noise (recommended for PR checks)

### IO and parsing
1. `load_data` legacy fixture (`Data/no_exchange_run_of_river`)
2. `load_data` zonal fixture (`Data/zonal_test`)
3. Zonal fallback load (`Data/zonal_test` with `Network=CopperPlateNetwork`) if easy to set up in benchmark fixture

### Model construction (no solve)
4. `initialize_model` legacy (24h)
5. `initialize_model` zonal (24h)
6. `build_baseline_dispatch` resiliency (24h)

### Postprocessing
7. `collect_results_from_model` legacy (after prepared solved model)
8. `collect_results_from_model` zonal (after prepared solved model)
9. `export_results` legacy and zonal (separate benchmarks)

## Tier B — end-to-end solve (nightly / manual PR deep check)

10. `run_solver` legacy (24h)
11. `run_solver` zonal (24h)
12. `run_baseline_dispatch` resiliency (24h)
13. `run_resiliency_evaluation` with short `hours` sample (serial: `n_workers=1`)
14. `evaluate_resiliency` end-to-end smoke (`n_hours=24`, small `hours` list)

## Phase 2 optional additions

15. Parametric 2-scenario sweep (`n_hours=24`) on zonal fixture
16. 168h variants for selected end-to-end tests (nightly only)

---

## Benchmark configuration guidance

Use conservative defaults first; tune later based on runtime.

Suggested flags for quick suite:

```bash
pytest tests/benchmarks -m "bench_quick" \
  --benchmark-json benchmark-results/quick.json \
  --benchmark-min-rounds=5 \
  --benchmark-warmup=on
```

Suggested flags for deep suite:

```bash
pytest tests/benchmarks -m "bench_deep" \
  --benchmark-json benchmark-results/deep.json \
  --benchmark-min-rounds=8 \
  --benchmark-warmup=on
```

### Marker convention

- `@pytest.mark.bench_quick` for Tier A tests
- `@pytest.mark.bench_deep` for Tier B tests

---

## Branch comparison workflow

## 1) Run on main

```bash
git checkout main
pytest tests/benchmarks -m "bench_quick or bench_deep" \
  --benchmark-json benchmark-results/bench-main.json
```

## 2) Run on PR branch

```bash
git checkout <pr-branch>
pytest tests/benchmarks -m "bench_quick or bench_deep" \
  --benchmark-json benchmark-results/bench-pr.json
```

## 3) Compare

Option A (pytest-benchmark compare):

```bash
pytest-benchmark compare \
  benchmark-results/bench-main.json \
  benchmark-results/bench-pr.json
```

Option B (custom script):

```bash
python scripts/bench_compare.py \
  --base benchmark-results/bench-main.json \
  --candidate benchmark-results/bench-pr.json
```

---

## Reporting and thresholds

Start with **report-only** mode for first 1-2 weeks to build baseline confidence.

Then apply soft thresholds:

- **Critical path regressions**: flag if runtime increases > 15%
- **Non-critical path regressions**: flag if runtime increases > 25%

Track:
- mean,
- median,
- stddev,
- ratio (PR/main),
- absolute delta.

Recommend storing “top 5 regressions” and “top 5 improvements”.

---

## Environment controls (important)

For fair branch comparison:

- same machine / runner type,
- same Python and dependency lock,
- same solver availability and version,
- minimize background processes,
- avoid thermal throttling / power mode drift,
- run each suite at least twice when validating surprising regressions.

Solver-specific note:
- keep solver options fixed and explicit in benchmark fixtures.

---

## CI integration plan

## Stage 1 (manual)
- Add workflow dispatch job `benchmark.yml`.
- Accept branch/ref input.
- Upload JSON artifact.

## Stage 2 (nightly)
- Run deep suite nightly on default branch.
- Store trend artifacts (e.g., last N runs).

## Stage 3 (PR advisory)
- Run quick suite on PR.
- Compare against main baseline artifact.
- Post markdown summary comment (non-blocking).

---

## Implementation plan and effort

## Phase 1: baseline framework (3–5 days)

1. Add `pytest-benchmark` + markers + benchmark conftest utilities.
2. Implement Tier A + selected Tier B core cases (10–13 tests).
3. Add branch compare script (`scripts/bench_compare.py`).
4. Add docs and usage examples.

Estimated effort: **3–5 days**

## Phase 2: hardening (+1–2 days)

1. Add optional parametric + 168h nightly cases.
2. Add threshold-based advisory summary.
3. Refine noisy tests / isolate flaky benchmarks.

Estimated effort: **+1–2 days**

Total initial rollout: **~1 week**.

---

## Suggested deliverables

1. `tests/benchmarks/*` benchmark suite
2. `scripts/bench_compare.py` comparison script
3. Optional CI workflow for manual benchmark runs
4. `docs/benchmark-plan.md` (this doc)

---

## Risks and mitigations

- **Noise from solver/runtime variability**
  - Mitigation: separate quick vs deep, control environment, run repeats.

- **Overly slow benchmark suite**
  - Mitigation: keep PR quick suite at 24h horizon and minimal scenarios.

- **False-positive regressions**
  - Mitigation: advisory-only phase first; introduce thresholds after baseline history.

- **Benchmark drift over time**
  - Mitigation: pin datasets, horizons, and solver options in fixtures.

---

## Next concrete steps (recommended order)

1. Add `pytest-benchmark` and markers.
2. Implement `test_bench_io.py` and `test_bench_model_build.py` first.
3. Add one solve benchmark each for legacy and zonal.
4. Add resiliency benchmarks (build + run).
5. Implement `bench_compare.py` and produce first main-vs-branch report.
6. Decide PR advisory threshold policy after collecting baseline runs.
