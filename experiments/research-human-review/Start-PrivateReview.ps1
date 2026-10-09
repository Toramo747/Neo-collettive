# OXIBAY: explicit private local review bootstrap. No raw case data leaves this PC.
[CmdletBinding()]
param([switch]$PlanOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'This launcher requires Windows.'
}

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).ProviderPath
$expectedBranch = 'experiment/research-human-blind-audit'
$activeBranch = (& git -C $repo branch --show-current)
if ($LASTEXITCODE -ne 0 -or $activeBranch.Trim() -ne $expectedBranch) {
    throw "Refusing to execute outside the pinned experimental branch: $expectedBranch"
}

$scriptPath = Join-Path $PSScriptRoot 'review.py'
$lockPath = Join-Path $repo 'requirements.lock'
if (-not (Test-Path -LiteralPath $scriptPath) -or -not (Test-Path -LiteralPath $lockPath)) {
    throw 'Review script or locked dependency manifest was not found.'
}

$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $launcher) {
    throw 'Python 3.12 launcher (py.exe) is missing. Install Python 3.12 first.'
}
& py -3.12 --version
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.12 is not available through py -3.12.'
}

$venvPath = Join-Path $env:LOCALAPPDATA 'OXIBAY-Review\venv'
$pythonExe = Join-Path $venvPath 'Scripts\python.exe'

if ($PlanOnly) {
    Write-Host 'OXIBAY review - no network or collection in PlanOnly mode.'
    Write-Host "Branch: $activeBranch"
    Write-Host "Repository: $repo"
    Write-Host 'The full collection will use up to 16 free public HN queries.'
    Write-Host 'Maximum 30 cases, in a new NTFS-restricted local directory.'
    return
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    & py -3.12 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to create the local Python virtual environment.'
    }
}

& $pythonExe -m pip install --disable-pip-version-check --require-hashes -r $lockPath
if ($LASTEXITCODE -ne 0) {
    throw 'Dependency installation failed; no collection was started.'
}

Push-Location $repo
try {
    & $pythonExe -m unittest -q test_research_human_review
    if ($LASTEXITCODE -ne 0) {
        throw 'Local isolation tests failed; no collection was started.'
    }

    $privateDir = Join-Path $env:LOCALAPPDATA ('OXIBAY-private\review-' +
        (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' +
        [Guid]::NewGuid().ToString('N').Substring(0, 8))

    # The Python collector creates a new directory, restricts its NTFS ACL and
    # only then writes its raw public-source text and private prediction key.
    & $pythonExe $scriptPath collect --private-dir $privateDir
    if ($LASTEXITCODE -ne 0) {
        throw "Collection failed. Inspect the private directory locally: $privateDir"
    }

    Write-Host ''
    Write-Host 'PRIVATE DATASET CREATED LOCALLY. DO NOT COMMIT OR UPLOAD.'
    Write-Host "Private folder: $privateDir"
    Write-Host 'Give each independent human reviewer only blind_cases.jsonl and'
    Write-Host 'their own reviewer_1.csv or reviewer_2.csv, never private_predictions.json.'
    Write-Host ''
    Write-Host 'After both human reviews are complete, run:'
    Write-Host ('& "' + $pythonExe + '" "' + $scriptPath +
        '" aggregate --private-dir "' + $privateDir + '"')
    Write-Host 'That aggregate is descriptive only, not independent proof or production evidence.'
}
finally {
    Pop-Location
}
