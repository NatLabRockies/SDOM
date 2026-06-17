<#
.SYNOPSIS
    Read the version from pyproject.toml and create + push a matching Git tag.

.DESCRIPTION
    Reads `project.version` from `pyproject.toml`, then creates an annotated
    Git tag `v<version>` and pushes it to `origin`. Pushing the tag triggers
    `.github/workflows/release.yml`, which verifies the tag matches
    `pyproject.toml` and creates the GitHub Release with notes.

    See `___deploy_sdom.md` for the full release runbook.

.PARAMETER Remote
    Git remote to push the tag to. Defaults to `origin`.

.PARAMETER DryRun
    Print the tag that would be created/pushed without making any changes.

.PARAMETER Force
    Skip the "are you on main with a clean tree?" safety checks.
    Use only if you know what you're doing.

.EXAMPLE
    pwsh scripts/release_tag.ps1
    # Reads version from pyproject.toml (e.g. 0.2.0), creates tag v0.2.0,
    # and pushes it to origin.

.EXAMPLE
    pwsh scripts/release_tag.ps1 -DryRun
    # Prints what would happen without tagging or pushing.
#>
[CmdletBinding()]
param(
    [string]$Remote = "origin",
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# --- Locate repo root (parent of this script's directory) ---
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

# --- Read version from pyproject.toml ---
$pyprojectPath = Join-Path $repoRoot "pyproject.toml"
if (-not (Test-Path $pyprojectPath)) {
    throw "pyproject.toml not found at $pyprojectPath"
}

# Use Python's tomllib for a robust parse (matches what the workflow does).
$version = & python -c "import tomllib; print(tomllib.loads(open(r'$pyprojectPath','rb').read().decode())['project']['version'])"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    throw "Failed to read project.version from pyproject.toml"
}
$version = $version.Trim()
$tag = "v$version"

Write-Host "pyproject.toml version: $version" -ForegroundColor Cyan
Write-Host "Tag to create/push:     $tag" -ForegroundColor Cyan

# --- Safety checks ---
if (-not $Force) {
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    if ($branch -ne "main") {
        throw "Current branch is '$branch', expected 'main'. Use -Force to override."
    }

    $status = git status --porcelain
    if ($status) {
        throw "Working tree is not clean. Commit or stash changes first. Use -Force to override."
    }

    # Make sure the local main is up to date with the remote.
    git fetch $Remote --quiet
    $localSha  = (git rev-parse "HEAD").Trim()
    $remoteSha = (git rev-parse "$Remote/main").Trim()
    if ($localSha -ne $remoteSha) {
        throw "Local main ($localSha) differs from $Remote/main ($remoteSha). Pull/push first. Use -Force to override."
    }
}

# --- Check the tag doesn't already exist ---
$existingLocal = git tag --list $tag
if ($existingLocal) {
    throw "Tag $tag already exists locally. Delete it first: git tag -d $tag"
}

$existingRemote = git ls-remote --tags $Remote "refs/tags/$tag"
if ($existingRemote) {
    throw "Tag $tag already exists on $Remote. Delete it first: git push --delete $Remote $tag"
}

# --- Create and push the tag ---
if ($DryRun) {
    Write-Host "[DRY-RUN] git tag -a $tag -m `"SDOM $tag`"" -ForegroundColor Yellow
    Write-Host "[DRY-RUN] git push $Remote $tag" -ForegroundColor Yellow
    return
}

Write-Host "Creating annotated tag $tag..." -ForegroundColor Green
git tag -a $tag -m "SDOM $tag"
if ($LASTEXITCODE -ne 0) { throw "git tag failed" }

Write-Host "Pushing $tag to $Remote..." -ForegroundColor Green
git push $Remote $tag
if ($LASTEXITCODE -ne 0) { throw "git push failed" }

Write-Host ""
Write-Host "Done. Watch the workflow:" -ForegroundColor Green
Write-Host "  https://github.com/NatLabRockies/SDOM/actions/workflows/release.yml" -ForegroundColor Green
