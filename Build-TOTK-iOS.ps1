[CmdletBinding()]
param(
    [string]$WorkspaceRoot = 'E:\TMP\switch\totk-workspace',
    [string]$OutputRoot = '',
    [string]$WorkDir = '',
    [ValidateRange(1, 64)][int]$Jobs = 4,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

# All external inputs and tools belong to the selected workspace.
$WorkspaceRoot = [IO.Path]::GetFullPath($WorkspaceRoot)
if (-not $OutputRoot) { $OutputRoot = Join-Path $WorkspaceRoot 'output\full-builds' }
if (-not $WorkDir) { $WorkDir = Join-Path $WorkspaceRoot 'cache\full-build' }
$gameBase = Join-Path $WorkspaceRoot 'inputs\games\TOTK-base.nsp'
$gameUpdate = Join-Path $WorkspaceRoot 'inputs\games\TOTK-update-1.4.3.nsp'
$keys = Join-Path $WorkspaceRoot 'inputs\keys\prod.keys'
$firmware = Join-Path $WorkspaceRoot 'inputs\firmware'
$toolsRoot = Join-Path $WorkspaceRoot 'tools'
$llvm = Join-Path $toolsRoot 'ios-cross\toolchain\windows\iphone\bin'
$sdk = Join-Path $toolsRoot 'ios-cross\iPhoneOS26.5.sdk'
$dotnet = Join-Path $toolsRoot 'dotnet\dotnet.exe'
$python = Join-Path $toolsRoot 'python\venv\Scripts\python.exe'
$cmake = Join-Path $toolsRoot 'python\venv\Scripts\cmake.exe'
$ninja = Join-Path $toolsRoot 'python\venv\Scripts\ninja.exe'
$bash = Join-Path $toolsRoot 'git\bin\bash.exe'
$make = Join-Path $llvm '..\busybox\bin\make.exe'
$metal = Join-Path $toolsRoot 'metal\bin\metal.exe'
$env:PATH = "$(Join-Path $toolsRoot 'git\cmd');$(Join-Path $toolsRoot 'git\bin');$env:PATH"
$metallib = Join-Path (Split-Path -Parent $metal) 'metallib.exe'
$builder = Join-Path $PSScriptRoot 'games\totk\ios\tools\build_ipa_windows.py'

function Test-BuildInputs {
    if (-not [IO.Path]::IsPathRooted($OutputRoot) -or -not [IO.Path]::IsPathRooted($WorkDir)) {
        throw '输出目录和工作目录必须使用绝对路径。'
    }
    $required = @(
        @{ Name = '构建脚本'; Path = $builder; Type = 'Leaf' },
        @{ Name = '游戏本体'; Path = $gameBase; Type = 'Leaf' },
        @{ Name = '游戏更新'; Path = $gameUpdate; Type = 'Leaf' },
        @{ Name = '密钥文件'; Path = $keys; Type = 'Leaf' },
        @{ Name = '固件目录'; Path = $firmware; Type = 'Container' },
        @{ Name = 'Python'; Path = $python; Type = 'Leaf' },
        @{ Name = '.NET'; Path = $dotnet; Type = 'Leaf' },
        @{ Name = 'CMake'; Path = $cmake; Type = 'Leaf' },
        @{ Name = 'Ninja'; Path = $ninja; Type = 'Leaf' },
        @{ Name = 'Git Bash'; Path = $bash; Type = 'Leaf' },
        @{ Name = 'Make'; Path = $make; Type = 'Leaf' },
        @{ Name = 'Metal 编译器'; Path = $metal; Type = 'Leaf' },
        @{ Name = 'metallib'; Path = $metallib; Type = 'Leaf' },
        @{ Name = 'iPhoneOS SDK'; Path = (Join-Path $sdk 'SDKSettings.json'); Type = 'Leaf' },
        @{ Name = 'LLVM clang'; Path = (Join-Path $llvm 'clang.exe'); Type = 'Leaf' },
        @{ Name = 'LLVM C++'; Path = (Join-Path $llvm 'x86_64-w64-mingw32-clang++.exe'); Type = 'Leaf' },
        @{ Name = 'LLVM lld'; Path = (Join-Path $llvm 'lld.exe'); Type = 'Leaf' }
    )
    foreach ($item in $required) {
        if (-not (Test-Path -LiteralPath $item.Path -PathType $item.Type)) {
            throw "找不到$($item.Name)：$($item.Path)"
        }
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw '找不到 Git。请将 Git 加入 PATH 后重试。'
    }
    if ($WorkDir -match '\s' -or $sdk -match '\s' -or $llvm -match '\s') {
        throw '工作目录、iPhoneOS SDK 和 LLVM 工具链路径不能包含空格。'
    }
}

if ($CheckOnly) {
    try {
        Test-BuildInputs
        Write-Host '所需路径检查通过。'
        Write-Host "工作目录：$WorkDir"
        Write-Host "结果目录：$OutputRoot"
        exit 0
    } catch {
        Write-Host "路径检查失败：$($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

$resultDir = $null
$lock = $null
$recording = $false
$exitCode = 1
try {
    Test-BuildInputs
    New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
    $lockPath = Join-Path $WorkDir '.windows-ipa-build.lock'
    try {
        $lock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch {
        throw "工作目录正在被另一个一键构建使用：$WorkDir"
    }

    New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    for ($i = 0; $i -lt 100; $i++) {
        $name = if ($i -eq 0) { "TOTK-$stamp" } else { 'TOTK-{0}-{1:D2}' -f $stamp, $i }
        $candidate = Join-Path $OutputRoot $name
        if (Test-Path -LiteralPath $candidate) { continue }
        try {
            $resultDir = (New-Item -ItemType Directory -Path $candidate -ErrorAction Stop).FullName
            break
        } catch {
            if (-not (Test-Path -LiteralPath $candidate)) { throw }
        }
    }
    if (-not $resultDir) { throw '无法创建唯一的时间戳结果目录。' }

    $log = Join-Path $resultDir 'build.log'
    Start-Transcript -LiteralPath $log | Out-Null
    $recording = $true
    $ipa = Join-Path $resultDir 'TOTK-v143.ipa'
    Write-Host "结果目录：$resultDir"
    Write-Host "工作缓存：$WorkDir"
    Write-Host '开始构建；请保持窗口打开，直到出现完成或失败提示。'

    $buildArgs = @(
        '--base', $gameBase, '--update', $gameUpdate, '--keys', $keys, '--firmware', $firmware,
        '--sdk', $sdk, '--toolchain', $llvm, '--metal', $metal, '--dotnet', $dotnet,
        '--cmake', $cmake, '--ninja', $ninja, '--bash', $bash, '--make', $make,
        '--work', $WorkDir, '--out', $ipa, '--jobs', [string]$Jobs
    )
    Push-Location -LiteralPath $PSScriptRoot
    $previousErrorAction = $ErrorActionPreference
    try {
        # Route native stdout and stderr through PowerShell so the transcript records both.
        # Windows PowerShell turns native stderr into error records; do not stop on warnings.
        $ErrorActionPreference = 'Continue'
        & $python -X utf8 -u $builder @buildArgs 2>&1 | ForEach-Object { "$_" }
        $buildStatus = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
        Pop-Location
    }
    if ($buildStatus -ne 0) { throw "构建程序退出，代码：$buildStatus。" }

    $verification = Join-Path $WorkDir 'verification.json'
    if (-not (Test-Path -LiteralPath $verification -PathType Leaf)) {
        throw "找不到构建验证结果：$verification"
    }
    $report = Get-Content -LiteralPath $verification -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($report.status -ne 'pass') { throw '构建验证没有通过，请查看日志。' }
    Copy-Item -LiteralPath $verification -Destination (Join-Path $resultDir 'verification.json')
    Write-Host ''
    Write-Host '构建和文件验证完成。IPA 尚未签名，也未在设备上运行。' -ForegroundColor Green
    Write-Host "IPA：$ipa"
    Write-Host "ROM 和 shader：$(Join-Path $resultDir 'TOTK-v143-GameData')"
    Write-Host "签名权限配置：$(Join-Path $resultDir 'TOTK-v143.entitlements.plist')"
    Write-Host "跳过的 shader：$($report.shaders.skipped)"
    if ($report.shaders.skipped -gt 0) {
        Write-Host '有 shader 翻译失败，请查看构建日志和 shader 清单。' -ForegroundColor Yellow
    }
    Write-Host "日志：$log"
    $exitCode = 0
} catch {
    Write-Host "构建失败：$($_.Exception.Message)" -ForegroundColor Red
    if ($resultDir) { Write-Host "结果和日志目录：$resultDir" }
} finally {
    if ($lock) { $lock.Dispose() }
    if ($recording) { Stop-Transcript | Out-Null }
}
exit $exitCode
