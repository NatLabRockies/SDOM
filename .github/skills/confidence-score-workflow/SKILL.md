---
name: confidence-score-workflow
description: "Score how well-defined a task is, ask one clarifying question at a time, and decide when to proceed. Use for requirement clarification and confidence-gated execution in any agent workflow."
argument-hint: "Describe the task type and confidence dimensions to score"
user-invocable: false
---

# Confidence Score Workflow

Reusable methodology for assessing task clarity and deciding whether to ask clarifying questions or proceed.

## Purpose
- Quantify how well-defined a task is.
- Drive clarification with one question at a time.
- Make uncertainty transparent to the user.

## Outcome
- A confidence score from 0.00 to 1.00 with rationale.
- Structured clarification loop until readiness threshold is met.
- Explicit proceed decision with assumptions when needed.

## Core Rubric

| Range | Meaning | Action |
|---|---|---|
| 0.00-0.30 | Critical information missing. | Ask one clarifying question. Do not propose a plan. |
| 0.31-0.60 | Significant gaps remain. | Ask one clarifying question. Do not propose a plan. |
| 0.61-0.85 | Minor gaps remain; assumptions possible but not preferred. | Ask one clarifying question. Do not propose a plan. |
| 0.85-0.94 | Mostly clear. | Ask next question and offer option to proceed with explicit assumptions. |
| 0.95-1.00 | Fully specified. | Present plan/task breakdown and request confirmation before execution. |

## Procedure

### 1. Define Task-Specific Dimensions
1. Define dimensions and weights that sum to 1.00.
2. Keep dimensions concrete and observable.
3. Include output format and constraints when relevant.

### 2. Score Each Dimension
1. Use 0 when missing/unknown.
2. Use full weight when fully specified.
3. Use partial credit for partially defined inputs.
4. Sum and round to two decimals.

### 3. Report Score Every Turn
Use this line at the top of every reply:

```text
Confidence: 0.XX / 1.00 - <one-line rationale>
```

### 4. Act by Rubric Threshold
1. 0.00-0.80: ask one clarifying question only.
2. 0.81-0.94: ask one clarifying question and offer proceed-with-assumptions option.
3. 0.95-1.00: provide plan/task breakdown and ask for explicit confirmation.

### 5. Clarification Loop
After each user answer:
1. Update the relevant dimension scores.
2. Recompute and report confidence.
3. Ask the next single clarifying question or move to confirmation.

## Clarifying Question Format

```text
Clarifying question (k of N estimated)

<single concrete question>

Why I need this: <one sentence>

Options (if applicable):
- (A) ...
- (B) ...
- (C) Other - please specify
```

## Best Practices
- Do not inflate scores to proceed faster.
- State what is known and unknown in the rationale.
- Ask exactly one question at a time.
- Document assumptions if proceeding at 0.81-0.94.
- Recompute score after every clarification.

## Anti-patterns
- Multiple clarifying questions in one turn.
- Reporting score without rationale.
- Proceeding below threshold without confirmation.
- Static score that is not updated after new user input.

## Agent Integration Template

```markdown
## Confidence Score Integration

This agent uses .github/skills/confidence-score-workflow/SKILL.md.

Task-specific dimensions:
- <Dimension 1> (0-0.XX)
- <Dimension 2> (0-0.XX)
- ...
- <Dimension N> (0-0.XX)

Total: 1.00

The agent reports confidence at the start of each interaction and after each clarification.
```
