# Optimization Modeler Memory

This file stores learnings, patterns, and decisions from optimization modeling tasks.

---

## ✍️ Mathematical writing standards

When you produce or edit a formulation:

1. **Sets** in calligraphic letters (`\mathcal{N}`, `\mathcal{B}`, …). Never reuse a lowercase index name as a cardinality. Cardinality is `|\mathcal{S}|`.
2. **Variables** lowercase Latin or established SDOM names (`Cap_s`, `SOC_{s,t}`, `P_{s,t}^{ch}`). State the **domain** (`\mathbb{R}_{\ge 0}`, `\{0,1\}`, `\mathbb{Z}_{\ge 0}`) and **units** for every variable.
3. **Parameters** uppercase Latin or Greek; bounds use `\overline{\cdot}` / `\underline{\cdot}`. State **units** for every parameter.
4. **Indices** must be quantified explicitly with `\forall t \in \mathcal{T}`, `\forall s \in \mathcal{S}`, etc. on every constraint.
5. **Derived sets** must be defined explicitly: e.g., `\mathcal{N}_{a,i} := \{ n \in \mathcal{N} : a_n = a, i_n = i \}` instead of overloaded `\sum_{n \in \{a,i\}}`.
6. **Soft constraints** must declare the slack variables as part of the variable list and the penalty parameter in the objective.
7. **KaTeX gotchas** (when writing Markdown for VS Code preview / Sphinx):
   - `aligned` allows only a single `&` per row. For multi-column constraint blocks use `array{rcll}`.
   - Avoid long multi-line `\min_{...}` subscripts; collapse onto one line or list decision variables in prose.
   - Always prefer `\left( ... \right)` for tall delimiters.
8. **Always include** in every new formulation document:
   - A "Notation conventions" section.
   - A per-section change-log when revising.
   - A "Confidence / open items" section at the end.
9. **Match the implementation** — if the user has Pyomo files in `src/sdom/models/`, the math must align with it (same sets, same constraint names where possible). Reference Pyomo names in parentheses, e.g., $Cap_s^E$ (`model.CapE[s]`).

---

## 🚫 Anti-patterns to avoid

- Producing math without a Notation conventions block.
- Conflating "capacity factor" with "thermal availability".
- Writing hard transmission limits without first asking whether the model should be allowed to violate them.
- Adding a dispatch-cost proxy without explicitly checking with the user that the optimization is otherwise indifferent.
- Using `\begin{aligned}` with two `&` per row in a Markdown file (KaTeX will silently fail to render).
- Restating the same constraint twice when one dominates the other (and not flagging the redundancy to the user).
- Reusing a lowercase index name as a cardinality (`\mathcal{N} := \{1,\dots,n\}` with `n` also being the index).
- Renaming or restructuring without first updating the memory and asking the user.
- Editing Python code files — defer to `code-implementer`.

---

## 📐 Formulation Decisions

### Established Conventions
*Notation and formulation choices made for SDOM*

### Trade-off Analyses
*Modeling trade-offs evaluated and conclusions*

---

## 🔢 Notation Standards

### Set Definitions
*Established set notation for SDOM*

| Symbol | Meaning | Established In |
|--------|---------|----------------|
| $\mathcal{T}$ | Time periods | Original SDOM |

### Variable Naming
*Variable naming conventions*

---

## 📊 Modeling Patterns

### Storage Constraints
*Common patterns for storage modeling*

### Capacity Expansion
*Patterns for investment decisions*

---

## ⚠️ Gotchas & Edge Cases

*Modeling pitfalls discovered*

---

## 📝 Notes

*General learnings and observations*
