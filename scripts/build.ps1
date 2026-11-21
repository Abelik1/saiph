# SPDX-License-Identifier: AGPL-3.0-or-later
param([string]$Python = 'python', [string]$Version = '0.1.0-source.0')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$buildRoot = Join-Path $repoRoot ('build\source-electron-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $buildRoot | Out-Null
$env:TEMP = Join-Path $buildRoot 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP | Out-Null
$env:npm_config_cache = Join-Path $buildRoot 'npm-cache'
$env:electron_config_cache = Join-Path $buildRoot 'electron-cache'
$env:PIP_CACHE_DIR = Join-Path $buildRoot 'pip-cache'
& $Python -m venv (Join-Path $buildRoot 'venv')
if ($LASTEXITCODE) { throw 'Python 3.12 could not create the isolated build environment.' }
$buildPython = Join-Path $buildRoot 'venv\Scripts\python.exe'
& $buildPython -m pip install -e ($repoRoot + '[hosted]') pyinstaller
if ($LASTEXITCODE) { throw 'The native service dependencies did not install.' }
& npm --prefix (Join-Path $repoRoot 'frontend') ci
if ($LASTEXITCODE) { throw 'Frontend dependencies did not install.' }
& npm --prefix (Join-Path $repoRoot 'desktop') ci
if ($LASTEXITCODE) { throw 'Desktop dependencies did not install.' }
& $buildPython (Join-Path $repoRoot 'scripts\build-native.py') --profile link --version $Version --workpath $buildRoot --distpath (Join-Path $buildRoot 'dist')
if ($LASTEXITCODE) { throw 'The Electron build did not finish.' }
$builtApp = (Resolve-Path -LiteralPath (Join-Path $buildRoot 'dist\Saiph')).Path
$expectedBuild = [IO.Path]::GetFullPath((Join-Path $buildRoot 'dist\Saiph'))
if ($builtApp -ine $expectedBuild -or -not $builtApp.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Build output escaped the source workspace.' }
$distRoot = Join-Path $repoRoot 'dist'
New-Item -ItemType Directory -Force -Path $distRoot | Out-Null
$destination = [IO.Path]::GetFullPath((Join-Path $distRoot 'Saiph'))
if ($destination -ine [IO.Path]::GetFullPath((Join-Path $repoRoot 'dist\Saiph'))) { throw 'Unexpected destination.' }
if (Test-Path -LiteralPath $destination) {
    $oldApp = (Resolve-Path -LiteralPath $destination).Path
    if ($oldApp -ine $destination -or -not $oldApp.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Existing output escaped the source workspace.' }
    Move-Item -LiteralPath $oldApp -Destination (Join-Path $buildRoot 'previous-Saiph')
}
Move-Item -LiteralPath $builtApp -Destination $destination
