<#
.SYNOPSIS
    Build the one-file Windows binary, dist\eyewall.exe, and check it with --selftest.

.DESCRIPTION
    Run from anywhere inside the repository, with the project virtual environment in .venv. Installs PyInstaller into
    it at the version in scripts\pyinstaller-version.txt, the one CI uses. The same eyewall.spec builds on Linux and macOS
    in .github/workflows/binaries.yml, which also runs for pull requests that touch the build.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'No .venv here: python -m venv .venv; .venv\Scripts\python -m pip install -e ".[dev]"' }

$pin = (Get-Content (Join-Path $PSScriptRoot 'pyinstaller-version.txt') -Raw).Trim()
& $python -m pip install --quiet tzdata textual-image "pyinstaller==$pin"
if ($LASTEXITCODE -ne 0) { throw 'pip install pyinstaller failed' }

& $python -m PyInstaller --noconfirm --clean --workpath .pyi-build eyewall.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

$exe = Join-Path $root 'dist\eyewall.exe'
& $exe --selftest
if ($LASTEXITCODE -ne 0) { throw 'dist\eyewall.exe --selftest failed' }
Write-Host "Built $exe ($([math]::Round((Get-Item $exe).Length / 1MB, 1)) MB)"
