# Windows 构建 iOS 版本（实验性）

[English](windows-ios-build.md)

Windows 构建工具面向《塞尔达传说：王国之泪》1.4.3，使用本项目的运行时、经过校验的代码改写、游戏补丁和 shader 翻译器。构建结果是**未签名的 IPA**；RomFS 镜像和设备用 shader 会写入单独的 `GameData` 文件夹。Windows 构建路径尚未通过设备安装和实际游玩验证。

## 所需环境

- Python 3.14，以及 `cryptography`、`lz4`、`capstone` 和 `Pillow`。
- .NET 10、Git 和 Git Bash、CMake、Ninja、GNU Make。
- 支持 Apple 目标平台的 Windows LLVM 工具链和 LLD，以及完整的 iPhoneOS SDK。
- Apple 的 Metal Developer Tools for Windows，包含 `metal.exe` 和 `metallib.exe`。SDK 和 Apple 工具需要另行准备。

配置 libvpx 时，源码、构建目录、SDK 和 LLVM 工具链的路径中都不能包含空格。首次使用需要联网获取固定版本的源码及 LibHac NuGet 包。请将工作目录放在游戏文件所在的磁盘，并预留空间存放解出的镜像、shader 缓存和最终的镜像副本。

## 一键构建

在本机双击仓库根目录的 `Build-TOTK-iOS.cmd`。它会调用 `Build-TOTK-iOS.ps1`，复用 `E:\TMP\switch\totk-windows-v9-work` 中的缓存，并在 `E:\TMP\switch\TOTK-builds\TOTK-yyyyMMdd-HHmmss` 创建新的结果文件夹（不覆盖以前的结果）。构建窗口在完成或失败后会等待按键。

每个结果文件夹包含未签名的 `TOTK-v143.ipa`、`TOTK-v143.entitlements.plist`、单独存放 ROM 和 shader 的 `TOTK-v143-GameData`、`verification.json` 和 `build.log`。输出会随实际完成的阶段生成；失败时查看 `build.log`。工作目录通过目录链接使用了 `totk-windows-work` 和 `totk-windows-tools` 中的部分文件，复用时需要保留它们。

也可在 PowerShell 中仅检查路径，或指定结果目录和主程序编译的并行任务数：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'E:\TMP\workspace\MacNativeGames\Build-TOTK-iOS.ps1' -CheckOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'E:\TMP\workspace\MacNativeGames\Build-TOTK-iOS.ps1' -OutputRoot 'E:\TMP\switch\MyBuilds' -Jobs 4
```

PowerShell 脚本开头列出了游戏、固件和工具路径，位置改变后可在那里修改。`-WorkDir` 可指定其他绝对路径；工作目录、SDK 和 LLVM 工具链路径不能包含空格。`-Jobs` 控制主程序及依赖的编译并行度，shader 编译会自行选择并行度。shader 输入改变时，工具会保留旧设备种子并使用新的种子目录；Metal 库通过内容哈希共享缓存。

## 手动构建示例

以下示例使用本机 `E:\TMP` 下已有的工具。在 `E:\TMP\workspace\MacNativeGames` 中打开 PowerShell 后运行；如你的路径不同，请相应修改参数：

```powershell
$tools = 'E:\TMP\workspace\nxnative\.webui-data\tools'
$llvm = "$tools\ios-cross\toolchain\windows\iphone\bin"
$py = 'E:\TMP\switch\totk-windows-tools\venv314\Scripts\python.exe'
& $py games/totk/ios/tools/build_ipa_windows.py `
  --base 'E:\TMP\switch\totk.nsp' --update 'E:\TMP\switch\totk1.4.3.nsp' `
  --keys 'E:\TMP\switch\prod.keys' --firmware 'E:\TMP\Firmware.22.1.0' `
  --sdk "$tools\ios-cross\iPhoneOS26.5.sdk" --toolchain $llvm `
  --metal 'E:\TMP\APPLE\Metal Developer Tools\bin\metal.exe' `
  --dotnet "$tools\dotnet\dotnet.exe" `
  --cmake 'E:\TMP\switch\totk-windows-tools\venv314\Scripts\cmake.exe' `
  --ninja 'E:\TMP\switch\totk-windows-tools\venv314\Scripts\ninja.exe' `
  --bash 'C:\Program Files\Git\bin\bash.exe' --make "$llvm\..\busybox\bin\make.exe" `
  --work 'E:\TMP\switch\TOTK-windows-build' --out 'E:\TMP\switch\TOTK.ipa'
```

工具会拒绝与仓库记录的 1.4.3 哈希不匹配的游戏代码或 RomFS 镜像。上例会在输出位置生成：

- `TOTK.ipa`：未签名的应用包。
- `TOTK.entitlements.plist`：签名时请求使用的权限配置。
- `TOTK-GameData/`：单独保存的 `romfs.bin`、shader 包分片及其标记文件。

shader 种子由玩家自己的游戏文件生成；清单会记录翻译器未能生成的条目。设备端没有 shader 翻译器，缺失的变体可能导致部分画面无法绘制。此构建路径不预编译针对具体设备的 pipeline archive，需要由设备自行准备。

## 安装和复制游戏数据

使用自己的签名工具签名并侧载后，通过文件共享工具将 `TOTK-GameData` **文件夹内的内容**复制到应用的 `Documents/GameData`。先复制数据文件，**最后复制** `romfs.sha256` 和 `shader-seed.txt`；应用使用这两个标记识别已完成的传输，并在下次启动时解包 shader 分片。

早期 Windows 构建可能将 `shader-seed.txt` 保存为 CRLF 换行，旧版 IPA 会因此误报没有着色器。现在的构建器写入 LF 换行，新版 IPA 也能读取旧标记；对已安装的旧版，只需替换为对应构建生成的 LF 格式标记，无需重新复制 ROM 或 shader 分片。

如果替换标记后日志显示 `FAIL: game data number`，旧 IPA 内的游戏资源配置也受换行格式影响，需要安装修复后的 IPA。新构建会检查并规范化应用内的文本配置；原有 ROM 和 shader 数据可以继续使用。

地底近处出现不造成伤害、随视角移动的假瘴气时，可对照上游 [#337](https://github.com/ly05010419/MacNativeGames/issues/337)：iPhone 的贴图降 mip 会让按整数坐标读取的数据遮罩错位。本地测试版移植了上游按着色器读取方式保留完整贴图的修复，保留既有 ROM 和 shader 包；该测试版尚待设备复测，上游 iPhone 17 也有症状未完全消失的反馈。

应用通过单独的 plist 请求扩展内存权限；签名工具和配置描述文件必须保留该权限，它才有可能生效。Windows 构建过程不会签名或安装应用。

如果尝试通过 LiveContainer 运行，文件应放入游戏所选容器的 `Documents/GameData`。客体应用的权限不会自动赋给 LiveContainer 宿主；需要检查宿主的内存权限。此 IPA 尚未在 LiveContainer 中实测，能否运行仍需验证。

## 工作目录和缓存

工作目录会保留提取结果、改写结果和编译缓存，供以后重复构建使用。只有在源码、编译器标识和输出哈希均匹配时，才会复用 Windows shader 翻译器。

如果提取或资源传输中断，请先检查不完整的输出，再决定是否移走或替换。工具只有在验证内容后才会复用已有的外部 `GameData` 文件夹，不会覆盖内容不同的文件夹。不要分享 IPA、RomFS、shader 种子、密钥或从游戏中提取的文件。

v9 shader 翻译链会排除控制段标识无效的 BAHS 候选记录，并包含来自 nxnative（`b3f25a0`）的动态纹理偏移修复，以及计算 shader 共享内存大小的传递；需要重新生成 shader 种子。仓库自带的 macOS 翻译器早于这项修改：如需使用 Mac 构建，请先在 Mac 上运行 `games/totk/tools/totk_xlate/publish_native.sh` 重新构建并标记翻译器。构建工具会拒绝未标记的旧版翻译器，避免把旧翻译结果标为 v9。
