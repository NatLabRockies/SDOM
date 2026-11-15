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
- Keep all module and package imports at module scope, never inside functions or methods. Follow PEP 8: place imports after the module docstring and any `__future__` imports, before module globals and constants; group standard-library, third-party, and local imports separately with blank lines, and use separate lines for separate module imports.
- Keep module and package dependencies acyclic: if package A imports any module from package B, package B must not import any module from package A, directly or transitively. Apply the same rule between modules within a package. Do not hide architectural cycles with local imports, dynamic imports, or `TYPE_CHECKING` guards; restructure ownership and dependency direction instead.
- Avoid hidden coupling: depend on explicit public contracts, not another module's private state or implementation details. An internal change to one class should not require unrelated consumers and their tests to change unless its public contract changes.
- Keep each Python script or module at or below 1,500 lines. Before creating or extending a file beyond this limit, or adding code to an already oversized file, stop and present module-splitting or refactoring options and their trade-offs to the user. Discuss the options and obtain approval for the approach before proceeding.

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
4. Before adding imports, check dependency direction for direct cycles (`A -> B -> A`) and indirect cycles (`A -> B -> C -> A`), including imports through package re-exports.
5. Break cycles by moving shared contracts or data into a lower-level module that imports neither consumer, injecting dependencies through those contracts, or moving cross-domain queries into an orchestration layer.
6. Investigate hidden coupling when an implementation-only change breaks unrelated tests. Remove assumptions about private fields, internal representations, or undocumented behavior rather than patching every consumer.

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
5. Confirm imports are at module scope and follow PEP 8 placement and grouping.
6. Check Python file lengths; confirm any work exceeding the 1,500-line limit followed the required user discussion and approval.
7. Confirm module and package dependencies remain acyclic and consumers use explicit public contracts rather than implementation details.

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

### Dependency Direction and Coupling Patterns

Anti-pattern: furniture imports workers to answer `table.isdoneby()`, while
workers imports furniture to answer `carpenter.whatdo()`. This creates a cycle,
even when the imports are spread across different modules in each package.

```python
# BAD: furn.py
from .workers import Carpenter


class Table:
    def isdoneby(self):
        return Carpenter.lookup(self._maker_id)


# BAD: workers.py
from .furn import Chair, Table


class Carpenter:
    def whatdo(self):
        return Table.find_by_maker(self) + Chair.find_by_maker(self)
```

Do not move these imports inside the methods to make the cycle load successfully.
Instead, separate shared relationship data from concrete classes. For example,
both modules can depend on an immutable record, and an orchestration layer can
provide the same records to furniture and workers. Neither domain imports the
other; the shared module imports neither domain.

```python
# GOOD: contracts.py
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkRecord:
    item_name: str
    maker_id: str


# GOOD: furn.py (Chair can use the same pattern)
from dataclasses import dataclass

from .contracts import WorkRecord


@dataclass(frozen=True)
class Table:
    work: WorkRecord

    def isdoneby(self) -> str:
        return self.work.maker_id


# GOOD: workers.py
from dataclasses import dataclass

from .contracts import WorkRecord


@dataclass(frozen=True)
class Carpenter:
    work: tuple[WorkRecord, ...]

    def whatdo(self) -> tuple[str, ...]:
        return tuple(record.item_name for record in self.work)
```

These are alternative design sketches, not a drop-in refactor preserving the
bad example's object-returning API. Preserve existing public behavior when
applying this pattern to production code.

Hidden-coupling anti-patterns include reading `table._parts`, assuming the order
of its internal collections, or copying its completion logic into `Carpenter`.
Prefer a documented public query or a small shared contract instead. If changing
Table's internal representation breaks many unrelated Carpenter tests, repair
the dependency boundary rather than encoding more implementation assumptions.

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
- Imports are at module scope and follow PEP 8.
- Module and package dependencies are acyclic, including transitive dependencies and package re-exports.
- Consumers rely on explicit public contracts; internal implementation changes do not require unrelated consumer changes.
- Python files stay within 1,500 lines, or the user has discussed the options and approved the approach before work exceeding the limit proceeds.

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
