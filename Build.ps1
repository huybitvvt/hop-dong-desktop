$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Missing .venv. Create the virtual environment and install requirements-dev.txt first.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath tools/create_demo.py
    if ($LASTEXITCODE -ne 0) { throw 'Sample asset build failed.' }
    & $pythonPath tools/create_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon build failed.' }
    & $pythonPath -m PyInstaller --noconfirm HopDongAI.spec
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    & $pythonPath tools/package_release.py
    if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }
}
finally {
    Pop-Location
}
