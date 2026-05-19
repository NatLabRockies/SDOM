---
name: python-documentation-workflow
description: "Create and review Python docstrings and Markdown docs. Use when updating NumPy docstrings, auditing documentation quality, writing docs sections, and validating documentation completeness."
argument-hint: "Describe the docs task, target files, and expected output"
user-invocable: false
---

# Python Documentation Workflow

Reusable workflow for documentation-only tasks in Python repositories.

## Purpose
- Standardize Python documentation using NumPy-style docstrings for functions, classes, and modules.
- Improve consistency for IDE help, documentation generators, and code reviews.

## Why NumPy Style
- Structured and consistent sections (`Parameters`, `Returns`, `Raises`, `Examples`).
- Readable in plain text and `help()` output.
- Well supported by Sphinx and similar tooling.
- Widely adopted in scientific and data-focused Python projects.

## Outcome
- Produce consistent NumPy-style docstrings for functions and classes.
- Keep Markdown documentation complete, navigable, and accurate.
- Return a concise change summary with quality checks.

## Use When
- Updating or adding Python docstrings.
- Auditing API docs for completeness.
- Writing or revising Markdown documentation.
- Reviewing docs quality after implementation changes.

## Constraints
- Do not implement product features or business logic.
- Limit edits to documentation artifacts (`.py` docstrings and `.md` files).

## Procedure

### 1. Gather Context
1. Read the target files and nearby examples to match local style.
2. Identify public APIs and user-facing behavior that need documentation.
3. Capture task-specific conventions from active agent and repository instructions.

### 2. Update Python Docstrings (NumPy)
1. Ensure each documented symbol has a one-line summary starting with a verb.
2. Add an extended description focused on behavior and intent.
3. Document parameters with types and constraints.
4. Document returns with type and meaning when values are returned.
5. Document raised exceptions when applicable.
6. Add `See Also`, `Notes`, and `References` when useful.
7. Add examples when usage could be ambiguous.

#### NumPy Section Breakdown
- `Summary` (required): one line, imperative mood.
- `Extended description` (recommended): behavior, assumptions, caveats.
- `Parameters` (required if applicable): `name : type` and clear descriptions.
- `Returns` (required if applicable): output type/name and meaning.
- `Raises` (optional): intentional exceptions and trigger conditions.
- `See Also` (optional): related functions for discoverability.
- `Notes` (optional): algorithms, formulas, performance considerations.
- `References` (optional): papers, standards, URLs.
- `Examples` (highly recommended): doctest-like usage examples.

#### Function Template
```python
def function_name(param1, param2, *, keyword_param=None):
    """Short one-line summary starting with verb.

    Extended description focused on behavior and intent.

    Parameters
    ----------
    param1 : type
        Description of param1.
    param2 : type
        Description of param2.
    keyword_param : type, optional
        Description of keyword_param. Default is None.

    Returns
    -------
    type
        Description of return value.

    Raises
    ------
    ValueError
        When input values are invalid.

    See Also
    --------
    related_function : Brief description of relationship.

    Notes
    -----
    Optional implementation notes, formulas, or caveats.

    References
    ----------
    .. [1] https://example.com/reference

    Examples
    --------
    >>> result = function_name(1, 2)
    >>> result
    3
    """
```

#### Class Template
```python
class ClassName:
    """Short one-line summary starting with verb.

    Extended description of the class purpose.

    Parameters
    ----------
    param1 : type
        Description of constructor parameter.

    Attributes
    ----------
    attr1 : type
        Description of public attribute.

    Methods
    -------
    method_name(param)
        Brief description of method purpose.

    Examples
    --------
    >>> obj = ClassName(param1="value")
    >>> obj.method_name()
    """
```

#### Module Template
```python
"""One-line summary of the module.

Extended description of module purpose and scope.

Classes
-------
ClassName
    Brief description.

Functions
---------
function_name
    Brief description.

Constants
---------
CONSTANT_NAME : type
    Description.

Examples
--------
>>> import module_name
>>> module_name.function_name(...)
"""
```

#### Type Hints and Docstrings
- Keep both type hints and docstrings.
- Type hints support static analysis; docstrings provide behavior context and usage guidance.

### 3. Update Markdown Docs
1. Keep heading hierarchy clean (`#`, `##`, `###`).
2. Ensure code blocks use language tags.
3. Keep links relative and current.
4. Align examples and terminology with the code.

### 4. Perform Quality Checks
1. Verify all changed symbols include complete docstring sections.
2. Confirm terms and naming are consistent across code and docs.
3. Confirm examples run conceptually and reflect actual signatures.
4. Confirm summary includes what changed and why.

### 5. Apply Style Rules
1. Use imperative mood in summaries (`Calculate...`, `Load...`, `Validate...`).
2. Capitalize and punctuate parameter descriptions.
3. Use 4-space indentation for wrapped descriptions.
4. Keep section spacing clean with one blank line between sections.

### 6. Check Common Parameter Patterns
1. File paths: `str or Path`.
2. Array-like inputs: `array-like of shape (...)`.
3. Enumerated choices: `{'opt1', 'opt2'}`.
4. Optional callbacks: `callable, optional` with signature notes.

### 7. Avoid Anti-patterns
1. Do not use overly terse summaries without sectioned details for non-trivial behavior.
2. Do not use `name(type):` syntax in NumPy sections.
3. Do not omit `Returns` when values are returned.

## Completion Criteria
- Docstrings follow NumPy structure and are internally consistent for all updated symbols.
- Markdown edits are readable, linked, and technically accurate.
- No feature logic changes were introduced.
- A final summary lists modified files and key documentation updates.

## Quick Validation Tools (Optional)
- `python -m doctest module_name.py`
- `pydocstyle module_name.py`

## Return Summary Format
```markdown
## Documentation Summary

### Task Completed
[Brief description]

### Files Modified
- path/to/file.py - Updated docstrings for [...]
- docs/path/file.md - Added/updated section on [...]

### Quality Checks
1. [Check performed]
2. [Check performed]

### Notes
[Assumptions, limitations, or follow-ups]
```
