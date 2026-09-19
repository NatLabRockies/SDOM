# Documenter Memory

This file stores learnings, patterns, and decisions from documentation tasks.

---

## 📝 Style Decisions

### Established Conventions
*Documentation style choices made for SDOM*

- Document zonal input optionality as a user-facing convention in `docs/source/user_guide/zonal_inputs.md`; describe the accepted CSV omission pattern and resulting model behavior without naming private normalization helpers.
- Lead new-user examples with the Infrasys System interface. State the v0.3.0 System-only migration as a planned deprecation while retaining the accurate v0.2.7 behavior that legacy dict-based workflows still run.
- Keep Mermaid diagrams as unstyled common-subset flowcharts with ASCII node IDs, concise labels, and explicitly labeled decision edges.
- Document VRE `MinCapacity` as the canonical optional MW lower bound in both general and zonal input guides; retain lowercase `capacity` as the upper bound and describe its Infrasys mapping as `min_active_power`.

### Exceptions
*Cases where standard conventions don't apply*

---

## 🔍 Review Findings

### Common Issues
*Recurring documentation problems found*

### Quality Patterns
*Examples of good documentation in codebase*

---

## 📚 Sphinx Configuration

### Build Tips
*Sphinx build learnings*

### Extension Usage
*Sphinx extensions and their configuration*

---

## 🔗 Cross-Reference Patterns

### Working References
*Cross-reference patterns that work*

### Broken References
*Reference issues encountered and fixes*

- Use `NatLabRockies/SDOM` for repository and license links; legacy `Omar0902/SDOM` URLs are obsolete.

---

## ⚠️ Gotchas & Edge Cases

*Documentation pitfalls discovered*

---

## 📝 Notes

*General learnings and observations*
