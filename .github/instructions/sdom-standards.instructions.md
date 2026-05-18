---
applyTo: "**"
description: "SDOM project conventions, coding standards, and shared knowledge for all agents"
---

# SDOM Project Standards

This instruction applies to all work in the SDOM (Storage Deployment Optimization Model) repository.

## Reusable Skills (Use Instead of Duplicating Guidance)

- `.github/skills/python-code-implementation-workflow/SKILL.md`
    - Use for TDD workflow, API signature discipline, single-responsibility patterns, and implementation anti-patterns.
- `.github/skills/python-documentation-workflow/SKILL.md`
    - Use for NumPy docstring structure, Markdown documentation workflow, and documentation quality checks.
- `.github/skills/confidence-score-workflow/SKILL.md`
    - Use for confidence scoring, one-question clarification loop, and proceed-threshold behavior.

Keep this file focused on SDOM-specific conventions and repository-wide standards.

## 📦 Project Structure

```
src/sdom/
├── __init__.py          # Public API exports
├── config_sdom.py       # Configuration and logging
├── constants.py         # Project constants
├── io_manager.py        # Data I/O operations
├── optimization_main.py # Main optimization runner
├── results.py           # Results handling
├── models/              # Pyomo optimization models
├── analytic_tools/      # Post-processing analysis
├── parametric/          # Parametric study API
└── common/              # Shared utilities
```

## 📐 API Design Rules

Use `.github/skills/python-code-implementation-workflow/SKILL.md` for full API design and implementation workflow.

SDOM enforcement points:
1. **Maximum 2 mandatory positional arguments** per function.
2. Use `*` to force keyword-only optional arguments.
3. Preserve backward compatibility for public APIs.

## 📝 Docstring Format (NumPy)

Use `.github/skills/python-documentation-workflow/SKILL.md` for NumPy docstring templates and documentation workflow.

SDOM enforcement points:
1. Public APIs must include complete NumPy-style docstrings.
2. Docstrings and docs must remain aligned with SDOM mathematical notation.

## 🏷️ Git Commit Convention

```
<type>(<scope>): <description>

Types: feat, fix, docs, refactor, test, perf, chore
```

## 📁 Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Module | lowercase_snake | `io_manager.py` |
| Class | PascalCase | `OptimizationResults` |
| Function | lowercase_snake | `load_data` |
| Constant | UPPER_SNAKE | `DEFAULT_SOLVER` |
| Test file | test_* | `test_io_manager.py` |

## 🔢 SDOM Mathematical Notation

| LaTeX | Pyomo | Description |
|-------|-------|-------------|
| $\mathcal{T}$ | `model.T` | Time periods (1-8760) |
| $\mathcal{S}$ | `model.ST` | Storage technologies |
| $Cap_s^E$ | `model.CapE[s]` | Energy capacity (MWh) |
| $SOC_{s,t}$ | `model.SOC[s,t]` | State of charge |

## 🧪 Testing

Use `.github/skills/python-code-implementation-workflow/SKILL.md` for TDD and test coverage workflow.

SDOM enforcement points:
- All new code must include tests in `tests/`.
- Prefer pytest fixtures that reflect SDOM data shapes.
- Include edge cases and error-path tests.

## 📚 Documentation

Use `.github/skills/python-documentation-workflow/SKILL.md` for documentation execution details.

SDOM enforcement points:
- Update docstrings for API changes.
- Update relevant `.md` files in `docs/`.
- Keep math notation consistent with SDOM standards.
