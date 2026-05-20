---
name: python-code-implementation-workflow
description: "Implement and refactor Python code with TDD, API signature discipline, and maintainable design. Use for feature development, bug fixes, test-first workflows, and quality-focused refactoring."
argument-hint: "Describe the implementation task, target modules, and acceptance criteria"
user-invocable: false
---

# Python Code Implementation Workflow

Reusable workflow for implementing Python code with predictable quality and test coverage.

## Outcome
- Deliver working code guided by tests.
- Keep APIs clear and stable.
- Preserve maintainability through small, focused functions.

## Use When
- Implementing new features.
- Fixing bugs.
- Refactoring with behavior preservation.
- Adding tests for existing logic.

## Constraints
- Follow Test-Driven Development (TDD) by default.
- Keep function design aligned with single responsibility.
- Use at most 2 mandatory positional arguments per function.
- Make all remaining parameters keyword-only.
- Preserve backward compatibility for public APIs unless explicitly approved.

## Performance Defaults (Vectorization-First)

For performance-sensitive data-processing and result-collection code:

- Prefer NumPy/pandas vectorization over Python row-by-row loops when behavior can be preserved.
- Prefer one-pass extraction into arrays (for example with `np.fromiter`) and reuse arrays for totals, filtering, and exports.
- Prefer constructing DataFrames once from column arrays instead of repeated list appends in loops.
- Prefer `reshape`/`repeat`/`tile` patterns for cartesian-index outputs (for example `(hour, tech)` and `(line, hour)`).
- Preserve exact output schema and column ordering when refactoring to vectorized paths.
- Use Python loops only when vectorization would materially reduce clarity or change semantics.

## Procedure

### 1. Define Behavior First
1. Identify acceptance criteria and edge cases.
2. Define expected inputs, outputs, and failure modes.
3. Determine whether API changes are required.

### 2. Apply TDD Cycle (Mandatory)
1. Write a failing test first.
2. Implement the smallest change needed to pass.
3. Refactor while keeping tests green.
4. Repeat for each behavior slice.

### 3. Enforce API Signature Rules
1. Keep maximum 2 mandatory positional arguments.
2. Use `*` to force keyword-only optional arguments.
3. Place the primary object first.
4. Use safe defaults for optional parameters.
5. Do not remove or reorder existing public parameters.

#### Signature Pattern
```python
def function_name(
    primary_object,
    secondary_input,
    *,
    option1=default1,
    option2=default2,
    verbose=False,
):
    """Implement behavior for a single responsibility."""
```

### 4. Keep Single Responsibility
1. Ensure each function has one clear purpose.
2. Extract helpers when a function starts handling multiple concerns.
3. Keep orchestration separate from transformation/validation logic.

### 5. Write and Expand Tests
1. Add unit tests for normal behavior.
2. Add edge-case tests (empty, boundary, null-like inputs).
3. Add error-path tests (exceptions and messages).
4. Parameterize repeated input/output checks.

### 6. Final Quality Pass
1. Run the relevant test suite.
2. Confirm no behavior regressions in touched areas.
3. Verify API compatibility and call-site impact.
4. Add or update NumPy-style docstrings for changed public functions.

## Patterns and Anti-patterns

### API Signature Patterns
```python
# GOOD

def run_operation(
    model,
    data,
    *,
    solver="highs",
    time_limit=3600,
    verbose=False,
):
    return solve(model, data, solver=solver, time_limit=time_limit, verbose=verbose)

# BAD: too many positional arguments

def run_operation(model, data, solver, time_limit, gap_tolerance, verbose):
    return solve(model, data, solver=solver, time_limit=time_limit, verbose=verbose)
```

### Single Responsibility Patterns
```python
# GOOD: validation and transformation are separated

def validate_input(data):
    if not data:
        raise ValueError("data cannot be empty")


def transform_data(data, *, scale=1.0):
    return [value * scale for value in data]


# BAD: multiple responsibilities mixed together

def process_data(data, scale=1.0, save_path=None):
    if not data:
        raise ValueError("data cannot be empty")
    transformed = [value * scale for value in data]
    if save_path:
        with open(save_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(str(transformed))
    return transformed
```

### Vectorization Patterns
```python
# GOOD: one-pass extraction + vectorized DataFrame build
values = np.fromiter((get_value(i) for i in idx), dtype=float, count=len(idx))
df = pd.DataFrame({"idx": np.asarray(idx), "value": values})

# BAD: row-by-row append in hot paths
rows = []
for i in idx:
    rows.append({"idx": i, "value": get_value(i)})
df = pd.DataFrame(rows)
```

### TDD Patterns
```python
# GOOD FLOW
# 1) Write failing test
# 2) Implement minimal code to pass
# 3) Refactor with tests still passing

# ANTI-PATTERN
# Write large implementation first, then add tests afterward.
```

## Completion Criteria
- TDD loop was followed for implemented behavior.
- Functions keep single responsibility.
- All new/changed signatures follow max-2-positional and keyword-only rules.
- Tests cover normal, edge, and error behavior for modified logic.
- Public API compatibility is preserved or explicitly documented.

## Return Summary Format
```markdown
## Implementation Summary

### Task Completed
[Brief description]

### Files Modified
- src/module.py - [changes]
- tests/test_module.py - [tests added/updated]

### TDD Evidence
1. [Failing test added]
2. [Implementation step]
3. [Refactor step]

### API Design Check
- Max positional arguments: Pass/Fail
- Keyword-only optional arguments: Pass/Fail
- Backward compatibility: Pass/Fail

### Test Coverage
- Unit tests: [count]
- Edge cases: [list]
- Error paths: [list]

### Notes
[Assumptions, trade-offs, follow-ups]
```
