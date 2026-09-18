# Orchestrator Memory

This file stores learnings, patterns, and context from orchestrator operations.

---

- System parametric plotting reconstructs metadata-ordered scenarios from `SDOMScenarioMetadata` and delegates rendering to `plot_parametric_results` through a minimal adapter exposing `case_metadata` and `output_dir`.
- `add_parametric_results_to_system` records `case_index`, `scenario_id`, `case_name`, and `sweep_values`, which are sufficient for grouping, hue, facet, and chunking behavior.

## 📅 Session Log

### 2026-09-17: PR #81 Copilot comments #1 and #4
**Task**: Fix zonal System time-series sweeps and zonal parametric System plotting.
**Routing**: code-implementer for comment #1; orchestrator completed comment #4 with focused TDD.
**Outcome**: Zonal tagged source and normalized per-area time series now scale together. Reconstructed zonal per-case summaries aggregate per-area metrics before legacy parametric plotting, including a correctly recomputed VRE curtailment percentage.
**Validation**: `uv run pytest tests/infrasys_integration/test_system_parametric.py tests/infrasys_integration/test_plotting.py -q` — 18 passed.

### 2026-09-18: Issue #85 optional zonal assets
**Task**: Permit zonal areas with demand/transmission but no optional technology assets.
**Routing**: code-implementer followed by documenter.
**Outcome**: The zonal per-area slice now normalizes absent optional partitions to empty schemas or zero fixed-generation profiles. Thermal generation correctly handles an empty plant set. The zonal input guide documents this contract.
**Validation**: `uv run pytest tests/test_zonal_model_build.py -v` — 13 passed.

### 2026-09-18: Issue #85 zonal outputs and plots
**Task**: Validate results export and standard/parametric plots for asset-free zonal areas.
**Routing**: code-implementer.
**Outcome**: Zonal result collection now builds the system-level `summary_df` consumed by standard CSV export, `plot_results`, and `plot_parametric_results`. Coverage uses an asset-free, transfer-supplied A1 with adequate temporary A2 generation and line capacity.
**Validation**: `uv run pytest tests/test_zonal_results_export_plotting.py -v` and existing zonal output suites.

### 2026-09-18: Documentation audit and Infrasys migration guidance
**Task**: Improve documentation accuracy and accessibility, add focused Mermaid diagrams, and establish System-first examples.
**Routing**: documenter.
**Outcome**: Canonical docs now state Python `>=3.11,<3.14`, link to NatLabRockies/SDOM, and correctly document zonal aggregate `summary_df`. README and docs landing pages include runnable System-first copperplate commands. Documentation announces that v0.3.0 will make the Infrasys System workflow the only supported workflow and deprecate the dict-based interface; it explicitly preserves current v0.2.7 compatibility.
**Validation**: `uv run pytest tests/test_docs_build.py -q` - 14 passed.

### 2026-04-21: Xpress Solver Integration
**Task**: Add Xpress commercial solver support to SDOM
**Routing**: code-implementer (primary) → documenter (docs update)
**Outcome**: Success - all tests passing
**Files changed**:
- `src/sdom/optimization_main.py` - Updated `configure_solver`, `get_default_solver_config_dict`
- `pyproject.toml` - Added xpress optional dependency
- `tests/test_no_resiliency_optimization_cases_xpress_local.py` - New test structure
- `docs/source/user_guide/running_and_outputs.md` - Added Xpress docs

---

## 🎯 Task Routing Patterns

### Successful Routings
*Record patterns that worked well*

- **New solver integration**: code-implementer handles API + tests, then documenter for docs
- Single agent (code-implementer) sufficient when task is primarily code with inline docs

### Routing Adjustments
*Record when initial routing needed adjustment*

---

## ❓ Clarification Patterns

### Effective Questions
*Questions that efficiently resolved ambiguity*

- For solver integration: Ask about license availability before implementation
- For new features: Ask about backward compatibility requirements

### Ambiguity Indicators
*Patterns in user requests that indicate need for clarification*

- "integrate X with Y" - need to clarify: which interface? what configuration options?

---

## 🔄 Inter-Agent Coordination

### Handoff Learnings
*What context is most useful between agents*

- When code-implementer finishes, pass: list of changed files, new API signatures, test coverage status

### Sequence Optimizations
*Efficient agent sequences for common tasks*

- **Feature + Docs**: code-implementer first (code + docstrings + tests), documenter second (md files only)
- **Pure refactor**: code-implementer only (if no API changes)

---

## 📝 Notes

*General learnings and observations*
