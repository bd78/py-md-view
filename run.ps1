<#
.SYNOPSIS
    Set up the virtual environment if needed, then run md-view.py.
.DESCRIPTION
    Creates .venv on first run and installs requirements.txt into it. The
    dependencies are installed again whenever requirements.txt changes.
    Every argument is passed through to md-view.py.
.EXAMPLE
    .\run.ps1 samples\demo.md
.EXAMPLE
    .\run.ps1 --dark samples\flow.mmd
.NOTES
    Author: bd78 (https://github.com/bd78)
#>

$ErrorActionPreference = 'Stop'

$root         = $PSScriptRoot
$venv         = Join-Path $root '.venv'
$python       = Join-Path $venv 'Scripts\python.exe'
$requirements = Join-Path $root 'requirements.txt'
# Copy of the requirements.txt last installed; shared with run.bat.
$stamp        = Join-Path $venv 'requirements.installed'

function Exit-WithError([string] $message) {
    Write-Host $message -ForegroundColor Red
    exit 1
}

# 1. Create the virtual environment on first run.
if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment in $venv"
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $venv
    } else {
        Exit-WithError 'Python 3.9+ was not found. Install it from https://www.python.org/ and try again.'
    }
    if ($LASTEXITCODE -ne 0) { Exit-WithError "Creating the virtual environment failed (exit code $LASTEXITCODE)." }
}

# 2. Install dependencies when requirements.txt is new or has changed.
$upToDate = (Test-Path $stamp) -and
            ((Get-FileHash $requirements).Hash -eq (Get-FileHash $stamp).Hash)
if (-not $upToDate) {
    Write-Host 'Installing dependencies from requirements.txt'
    & $python -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) { Exit-WithError "pip install failed (exit code $LASTEXITCODE)." }
    Copy-Item $requirements $stamp
}

# 3. Run the viewer with every argument passed through.
& $python (Join-Path $root 'md-view.py') @args
exit $LASTEXITCODE
