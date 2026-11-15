param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$buildOutput = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
if (-not $buildOutput.StartsWith(($projectRoot.TrimEnd('\') + '\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build output must stay within this project.'
}
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
    & $pythonPath -m PyInstaller --noconfirm --distpath $buildOutput HopDongAI.spec
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    $appDirectory = Join-Path $buildOutput 'HopDongAI'
    & $pythonPath tools/package_release.py --app-dir $appDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }
    $launcherFolder = Join-Path $projectRoot 'dist'
    [IO.Directory]::CreateDirectory($launcherFolder) | Out-Null
    [IO.File]::WriteAllText((Join-Path $launcherFolder 'current-app.txt'), (Join-Path $appDirectory 'HopDongAI.exe'), [Text.UTF8Encoding]::new($false))
}
finally {
    Pop-Location
}
