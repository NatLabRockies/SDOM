---
applyTo: "**"
description: "SDOM project conventions, coding standards, and shared knowledge for all agents"
---

# SDOM Project Standards

This instruction applies to all work in the SDOM (Storage Deployment Optimization Model) repository.

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

1. **Maximum 2 mandatory positional arguments** per function
2. Use `*` separator to force keyword-only arguments
3. Primary object (data being acted upon) comes first
4. Maintain backward compatibility for public APIs

```python
def function_name(
    primary_object,
    secondary_input,
    *,
    option1=default1,
    verbose=False,
):
    pass
```

## 📝 Docstring Format (NumPy)

All functions and classes MUST use NumPy docstring format:

```python
def function_name(param1, *, option=None):
    """Short one-line summary starting with verb.

    Extended description.

    Parameters
    ----------
    param1 : type
        Description.
    option : type, optional
        Description. Default is None.

    Returns
    -------
    type
        Description.

    Raises
    ------
    ValueError
        When invalid input.

    Examples
    --------
    >>> result = function_name(x)
    """
    pass
```

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

- All new code must have tests in `tests/`
- Use pytest fixtures for SDOM data
- Test edge cases and error handling

## 📚 Documentation

- Update docstrings for any API changes
- Update relevant `.md` files in `docs/`
- Math notation must match SDOM standards
