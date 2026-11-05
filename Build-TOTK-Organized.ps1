[CmdletBinding()]
param(
    [string]$WorkspaceRoot = 'E:\TMP\switch\totk-workspace',
    [ValidateRange(1, 64)][int]$Jobs = 4,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$root = [IO.Path]::GetFullPath($WorkspaceRoot)
$tool = Join-Path $root 'tools'
$cache = Join-Path $root 'cache\totk-1.4.3'
$resources = Join-Path $root 'game-resources\totk-1.4.3'
$py = Join-Path $tool 'python\venv\Scripts\python.exe'
$llvm = Join-Path $tool 'ios-cross\toolchain\windows\iphone\bin'
$sdk = Join-Path $tool 'ios-cross\iPhoneOS26.5.sdk'
$scripts = Join-Path $PSScriptRoot 'games\totk\ios\tools'
$required = @($py, (Join-Path $llvm 'x86_64-w64-mingw32-clang.exe'), (Join-Path $llvm 'lld.exe'),
    (Join-Path $sdk 'SDKSettings.json'), (Join-Path $cache 'export\embed.o'),
    (Join-Path $cache 'export\ios_embed.h'), (Join-Path $cache 'export\embed.S'),
    (Join-Path $tool 'codecs\opus-src\include\opus.h'), (Join-Path $tool 'codecs\vpx-src\vpx\vpx_decoder.h'),
    (Join-Path $tool 'codecs\opus-build\libopus.a'), (Join-Path $tool 'codecs\vpx-build\libvpx.a'),
    (Join-Path $cache 'raw-v143\icon.jpg'), (Join-Path $resources 'romfs-index\index.json'),
    (Join-Path $resources 'runtime-tree\build\game-data\v143\runtime-tables.bin'),
    (Join-Path $resources 'game-data\romfs.bin'))
foreach ($path in $required) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing input: $path" } }
if ($CheckOnly) { Write-Host 'Cached rebuild inputs are present.'; exit 0 }
function Run-Tool([string]$Script, [string[]]$ToolArgs) {
    & $py -X utf8 -u (Join-Path $scripts $Script) @ToolArgs
    if ($LASTEXITCODE -ne 0) { throw "$Script failed with exit code $LASTEXITCODE" }
}
$objectDir = Join-Path $cache 'objects-current'
$binary = Join-Path $cache 'linked\TOTK'
$out = Join-Path $root ('output\build-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Force -Path $out, (Split-Path -Parent $binary) | Out-Null
$ipa = Join-Path $out 'TOTK-v143-settings.ipa'
Run-Tool 'windows_compile.py' @('--clang', (Join-Path $llvm 'x86_64-w64-mingw32-clang.exe'), '--sdk', $sdk,
    '--generated', (Join-Path $cache 'export'), '--opus-include', (Join-Path $tool 'codecs\opus-src\include'),
    '--vpx-include', (Join-Path $tool 'codecs\vpx-src'), '--out', $objectDir, '--jobs', [string]$Jobs)
Run-Tool 'windows_link.py' @('--lld', (Join-Path $llvm 'lld.exe'), '--sdk', $sdk, '--objects', $objectDir,
    '--embed', (Join-Path $cache 'export\embed.o'), '--opus', (Join-Path $tool 'codecs\opus-build\libopus.a'),
    '--vpx', (Join-Path $tool 'codecs\vpx-build\libvpx.a'), '--out', $binary)
Run-Tool 'windows_pack_ipa.py' @('--executable', $binary, '--tree', (Join-Path $resources 'runtime-tree'),
    '--romfs', (Join-Path $resources 'romfs-index'), '--icon', (Join-Path $cache 'raw-v143\icon.jpg'), '--out', $ipa)
$dest = Join-Path $out 'GameData'
Copy-Item -LiteralPath (Join-Path $resources 'game-data') -Destination $dest -Recurse
Run-Tool 'verify_windows_output.py' @('--ipa', $ipa, '--game-data', $dest, '--report', (Join-Path $out 'verification.json'))
Write-Host "Unsigned IPA and verified GameData: $out"
