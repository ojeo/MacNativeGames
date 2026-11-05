# Experimental Windows iOS build

The Windows builder targets Tears of the Kingdom 1.4.3. It uses this project's runtime, verified rewrites, game
patches and shader translator. The result is an unsigned IPA; the RomFS image and device shaders are written to a
separate `GameData` folder. The Windows path has not yet been validated by installing and playing on a device.

The builder needs Python 3.14 with `cryptography`, `lz4`, `capstone` and `Pillow`, .NET 10, Git and Git Bash,
CMake and Ninja, GNU Make, a Windows LLVM toolchain with an Apple target and LLD, a complete iPhoneOS SDK, and Apple's
Metal Developer Tools for Windows (`metal.exe` and `metallib.exe` together). The SDK and Apple tools are supplied
separately. The libvpx configure step requires the source, build, SDK and LLVM paths to have no spaces. First use needs
network access for pinned source checkouts and the LibHac NuGet package. Use a work folder on the game drive with room
for the extracted image, the shader cache and the final copy of the image.

To build with the paths on this machine, double-click `Build-TOTK-iOS.cmd` in the repository root. It runs
`Build-TOTK-iOS.ps1`, uses `E:\TMP\switch\totk-workspace` for inputs, tools and cache, and creates a new timestamped folder under
`E:\TMP\switch\totk-workspace\output\full-builds` with the IPA, external GameData, requested entitlements, `build.log` and
`verification.json`. The output is unsigned. To check prerequisites without building, run
`powershell -ExecutionPolicy Bypass -File .\Build-TOTK-iOS.ps1 -CheckOnly`.

The PowerShell script accepts `-WorkspaceRoot`, `-OutputRoot`, `-WorkDir` and `-Jobs`. For a faster rebuild using
the verified 1.4.3 exported game code and existing resources, use `Build-TOTK-Organized.ps1` in the repository root.
Its output is unsigned and it verifies the IPA and external data. It does not regenerate game code or shaders.
After moving the workspace, run `Setup-TOTK-Python.ps1 -WorkspaceRoot <new-path>` to recreate its virtual
environment from the local wheelhouse; the script preserves the previous environment as a backup.
When shader inputs change, the full builder preserves the old device seed and creates a separate one, while
reusing content-addressed Metal libraries where possible.

For example, to invoke the Python builder directly using tools already installed under `E:\TMP`:

```powershell
$root = 'E:\TMP\switch\totk-workspace'
$tools = "$root\tools"
$llvm = "$tools\ios-cross\toolchain\windows\iphone\bin"
$py = "$tools\python\venv\Scripts\python.exe"
& $py games/totk/ios/tools/build_ipa_windows.py `
  --base "$root\inputs\games\TOTK-base.nsp" --update "$root\inputs\games\TOTK-update-1.4.3.nsp" `
  --keys "$root\inputs\keys\prod.keys" --firmware "$root\inputs\firmware" `
  --sdk "$tools\ios-cross\iPhoneOS26.5.sdk" --toolchain $llvm `
  --metal "$tools\metal\bin\metal.exe" `
  --dotnet "$tools\dotnet\dotnet.exe" `
  --cmake "$tools\python\venv\Scripts\cmake.exe" `
  --ninja "$tools\python\venv\Scripts\ninja.exe" `
  --bash "$tools\git\bin\bash.exe" --make "$llvm\..\busybox\bin\make.exe" `
  --work "$root\cache\full-build" --out "$root\output\TOTK.ipa"
```

The builder rejects game code and RomFS images that do not match the repository's 1.4.3 hashes. It creates
`TOTK.ipa`, `TOTK.entitlements.plist` and `TOTK-GameData/` beside the output IPA. The separate folder contains
`romfs.bin`, shader pack parts and their marker files. The seed is prepared from the player's own game files; its
manifest records any translations the shader translator could not produce. The device has no shader translator, so
missing variants can cause missing draws. This path does not precompile device-specific pipeline archives; the device
must prepare those itself.

After sideloading with the user's own signing tool, transfer the contents of `TOTK-GameData` to the app's
`Documents/GameData` through a file-sharing tool. Copy `romfs.sha256` and `shader-seed.txt` **after** their data files;
the app uses these markers to recognize complete transfers and unpacks the shader parts at the next launch. The app
requests the increased-memory entitlement in the separate plist. A signing tool and provisioning profile must preserve
that entitlement for it to be effective; the Windows build does not sign or install the app.

Earlier Windows builds could write `shader-seed.txt` with CRLF line endings, which older IPAs rejected as missing
shaders. The builder now writes LF, and the newer IPA also accepts the old marker. For an already installed older IPA,
replace only the marker with the matching LF version; the ROM and shader parts do not need to be copied again.

If an older IPA then exits with `FAIL: game data number`, its embedded game-data configuration also has Windows line
endings; install the fixed IPA. New builds normalize and verify runtime text metadata, and can use the existing ROM and
shader data.

The work folder retains the extraction, rewrites and compiler caches for later runs. The Windows translator is reused
only when its source, compiler identity and output hashes still match. If an extraction or resource
transfer is interrupted, inspect its partial output before removing or replacing it. The builder reuses an existing
external `GameData` folder only after verifying its contents; it does not overwrite a different one. Never share the IPA,
RomFS, shader seed, keys or extracted game files.

The v9 shader chain rejects invalid BAHS control records and carries the dynamic texture-offset fix from nxnative
(`b3f25a0`), including each compute shader's shared-memory size. It requires a newly prepared seed. The bundled macOS
translator predates this change: on a Mac, run `games/totk/tools/totk_xlate/publish_native.sh` to rebuild and stamp it
before using the Mac builder. The build rejects an unstamped prebuilt instead of labeling old translations as v9.
