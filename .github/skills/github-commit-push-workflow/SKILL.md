---
name: github-commit-push-workflow
description: "Create, review, and push focused Git commits using GitHub CLI and Conventional Commits. Use when preparing commits, splitting a change into atomic commits, pushing a branch, checking GitHub authentication or repository state, or creating a pull request."
argument-hint: "Describe the changes to commit, target branch, and whether to push or open a pull request"
user-invocable: true
---

# GitHub Commit and Push Workflow

Prepare reviewable, independently understandable commits and publish them through GitHub CLI.

## Outcome
- Each commit is an atomic, validated change that can be reviewed, reverted, and cherry-picked independently.
- Commit messages follow Conventional Commits.
- GitHub interactions use `gh`; do not use the GitHub website or other GitHub clients.
- A branch is pushed only after its commit history and working tree are reviewed.

## Tool Rules
- Use `gh` for GitHub authentication, repository information, pull requests, issues, releases, and GitHub-hosted checks.
- Use Git only for local repository operations that `gh` does not provide, including staging, committing, inspecting diffs, rebasing, and pushing refs.
- Before a GitHub operation, verify authentication with `gh auth status` when authentication has not already been confirmed in the session.
- Do not expose tokens, credentials, or private remote URLs in output.
- Do not force-push unless the user explicitly requests it. When an explicitly approved history rewrite must be pushed, use `git push --force-with-lease`, never `--force`.

## Procedure

### 1. Inspect the Change Set
1. Confirm repository and branch state with `git status --short --branch`.
2. Confirm the GitHub repository with `gh repo view --json nameWithOwner,url`.
3. Inspect the complete diff and identify each independently meaningful behavior, refactor, test, documentation, build, or operational change.
4. Preserve user changes. Never reset, restore, or discard work that is unrelated to the requested commit.

### 2. Plan Atomic Commit Slices
Create a separate commit for each slice that has one purpose and can stand on its own.

Split commits when changes differ by:
- behavior or feature;
- bug fix;
- refactor with no behavior change;
- tests for existing behavior versus tests coupled to a new behavior;
- documentation;
- build, dependency, CI, or operational configuration;
- generated artifacts that can be reproduced separately.

Keep changes together when separating them would make either commit fail, break tests, or obscure the intent. For example, a feature and the tests that prove that feature normally belong in one commit.

Order dependent slices so each commit leaves the repository in a working state:
1. required mechanical preparation or safe refactor;
2. behavior change with its directly coupled tests;
3. independent test expansion;
4. documentation or generated outputs.

Do not combine unrelated formatting, drive-by cleanup, dependency upgrades, generated files, secrets, local settings, or unrelated user changes into a commit.

### 3. Stage and Verify Each Slice
1. Stage only the intended paths or hunks with `git add <paths>` or `git add -p`; never use `git add .` or `git add -A` for a scoped change.
2. Review exactly what will be committed with `git diff --cached --check` and `git diff --cached`.
3. Run the narrowest relevant test, lint, typecheck, build, or validation command for the staged change.
4. Confirm `git status --short` still separates staged work from remaining work as intended.
5. If validation fails, fix the current slice and repeat the staged review before committing.

### 4. Write the Commit Message

Use this general format from the [Conventional Commits Cheatsheet](https://gist.github.com/qoomon/5dfcdf8eec66a051ecd85625518cfd13):

```text
<type>(<optional scope>): <description>

<optional body>

<optional footer>
```

Use this command template:

```sh
git commit -m "<type>(<scope>): <description>" -m "<body>" -m "<footer>"
```

Message rules:
- Select one type: `feat`, `fix`, `refactor`, `perf`, `style`, `test`, `docs`, `build`, `ops`, or `chore`.
- Use a scope only when it names a stable project area; never use an issue identifier as a scope.
- Write a mandatory, concise description in imperative present tense, starting lowercase and without a final period.
- Use the optional body to explain motivation and contrast prior behavior when that context matters.
- Add issue references in the footer, for example `Closes #123`.
- Mark breaking changes with `!` before `:` and include a `BREAKING CHANGE:` footer.

Examples:

```text
feat(case-assembly): add zonal hydro input validation
fix(pras): preserve outage rates during export
refactor(results): separate hourly aggregation
test(case-assembly): cover missing generator categories
docs: document scenario input conventions
build: update solver dependency
```

### 5. Commit and Review History
1. Create the commit with the approved message.
2. Review it using `git show --check --stat HEAD` and `git show HEAD`.
3. Repeat staging, validation, and review for every remaining slice.
4. Before publishing, confirm a clean or intentionally understood working tree with `git status --short --branch`.
5. Review commits that will be published with `git log --oneline @{upstream}..HEAD` when an upstream exists; otherwise review the branch history relative to its base branch.

### 6. Push and Confirm on GitHub
1. Fetch remote state with `git fetch origin`.
2. Rebase or resolve divergence before pushing when required by the repository workflow; rerun relevant validation after a rebase.
3. Push a new branch with `git push -u origin HEAD`, or push an established upstream branch with `git push`.
4. Confirm the remote branch through GitHub CLI with `gh repo view` and `gh pr status`.
5. When requested, create the pull request with `gh pr create` and include a concise title, summary, validation evidence, and issue-closing footer/reference where applicable.

## Completion Criteria
- Every commit has one coherent purpose and contains no unrelated changes.
- Each committed slice has been reviewed with `git diff --cached` before commit and `git show` after commit.
- Relevant validation passed for every behavioral or configuration slice.
- Commit subjects conform to `<type>(<optional scope>): <description>`.
- GitHub-facing actions were performed with `gh`.
- The branch was pushed without force unless the user explicitly approved a `--force-with-lease` push.

## Return Summary Format

```markdown
## Commit and Push Summary

### Commits
- `<sha>` `<type>(<scope>): <description>`

### Validation
- `<command>`: passed

### GitHub
- Branch: `<branch>`
- Push: completed
- Pull request: `<URL or not created>`

### Remaining Work
- [Uncommitted changes or none]
```