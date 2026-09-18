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
