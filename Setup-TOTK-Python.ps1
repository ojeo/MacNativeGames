[CmdletBinding()]
param([string]$WorkspaceRoot = 'E:\TMP\switch\totk-workspace')
$ErrorActionPreference = 'Stop'
$folder = Join-Path ([IO.Path]::GetFullPath($WorkspaceRoot)) 'tools\python'
$base = Join-Path $folder 'base\python.exe'
$venv = Join-Path $folder 'venv'
$wheels = Join-Path $folder 'wheels'
$requirements = Join-Path $folder 'requirements.txt'
foreach ($p in @($base, $wheels, $requirements)) {
    if (-not (Test-Path -LiteralPath $p)) { throw "Missing Python setup input: $p" }
}
if (Test-Path -LiteralPath $venv) {
    $backup = Join-Path $folder ('venv-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    if (Test-Path -LiteralPath $backup) { throw "Backup already exists: $backup" }
    Move-Item -LiteralPath $venv -Destination $backup
    Write-Host "Previous environment preserved: $backup"
}
& $base -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
$py = Join-Path $venv 'Scripts\python.exe'
& $py -m pip install --no-index --find-links $wheels -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Offline Python dependency installation failed' }
Write-Host "Python environment ready: $venv"
