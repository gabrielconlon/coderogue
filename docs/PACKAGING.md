# Packaging

CodeRogue ships as a PyInstaller **one-folder** build: no Python install is needed to play.
macOS gets a `.app` bundle, Windows a folder with `CodeRogue.exe` (both windowed, no console),
Linux a folder with a `CodeRogue` console binary.

## Build locally

All platforms, from the repo root, in a venv with the game installed:

```sh
pip install -e ".[build]"            # PyInstaller
python tools/fetch_assets.py         # Kenney packs into assets/kenney/ (required)
python tools/fetch_runtime.py        # standalone CPython 3.13 into runtime/python/ (optional)
python tools/build.py                # add --clean to drop PyInstaller's cache
```

| OS | Output | Launch |
|---|---|---|
| macOS | `dist/CodeRogue.app` | `open dist/CodeRogue.app` or `dist/CodeRogue.app/Contents/MacOS/CodeRogue` |
| Windows | `dist\CodeRogue\CodeRogue.exe` | double-click, or `Start-Process -Wait` (it is a GUI exe) |
| Linux | `dist/CodeRogue/CodeRogue` | run it from a terminal or a launcher |

On macOS PyInstaller also leaves an intermediate `dist/CodeRogue/` folder; ship only the `.app`.

`tools/build.py` renders `tools/coderogue.spec.in` into `build/CodeRogue.spec` (the template
fills every path in as a Python literal, so there is no `--add-data` quoting to get wrong on
Windows), runs PyInstaller with `build/` as its work dir and `dist/` as output, copies the
runtime in, and prints the output path and size. An icon is used only if
`assets/icon/coderogue.icns` (macOS) or `assets/icon/coderogue.ico` (Windows) exists.

Check any build with the hidden `--doctor` flag:

```sh
CODEROGUE_HOME=$(mktemp -d) dist/CodeRogue.app/Contents/MacOS/CodeRogue --doctor
CODEROGUE_HOME=$(mktemp -d) dist/CodeRogue.app/Contents/MacOS/CodeRogue --headless-frames 60 --new
```

`--doctor` prints the resource root, checks the content and asset files, and runs a one-line
program through the real sandbox in every language it finds. It exits 1 if a required file
is missing or the detected Python cannot run.

## What gets bundled

| Bundle path (under `sys._MEIPASS`) | Source | Notes |
|---|---|---|
| `content/` | `content/` | maps, puzzles, dialogue, `quests.yaml` |
| `assets/fonts/` | `assets/fonts/` | committed |
| `assets/kenney/` | `assets/kenney/` | CC0, fetched, gitignored; the build refuses to run without it |
| `runtime/python/` | `runtime/python/` | only if `tools/fetch_runtime.py` was run |
| Python, pygame-ce, SDL, PyYAML | the venv | collected by PyInstaller (pygame-ce ships its own hook) |

`coderogue.app.resource_path(*parts)` joins onto `sys._MEIPASS` when frozen and the repo root
otherwise, so `resource_path("content", "maps")` works unchanged in both. In a PyInstaller 6
one-folder build `sys._MEIPASS` is `<dist>/CodeRogue/_internal` (Windows, Linux) or
`CodeRogue.app/Contents/Frameworks` (macOS, where PyInstaller puts data in
`Contents/Resources` and symlinks it from `Frameworks`). The runtime follows the same split
on macOS: it is copied to `Contents/Resources/runtime/python` with a
`Contents/Frameworks/runtime` symlink. It is copied after PyInstaller runs, not through
`datas`, so the interpreter keeps its own layout and symlinks. `build.py` then re-seals the
`.app` with an ad-hoc signature.

Saves never go in the bundle: they live in the per-user data dir (`CODEROGUE_HOME` overrides).

## Running player Python in a frozen build

In development, player Python runs with `sys.executable`. In a frozen build that is the game's
bootloader, so `coderogue/languages/python.py` uses this chain instead:

1. **Bundled runtime**: `resource_path("runtime", "python", ...)` (`bin/python3`, or
   `python.exe` on Windows), a python-build-standalone CPython 3.13 `install_only` build
   fetched by `tools/fetch_runtime.py` (SHA-256 checked against the release, the test
   suite, tkinter, headers and pip pruned: about 46 MB unpacked on macOS arm64).
2. **PATH**: every `python3` and `python` on `PATH`, then `/opt/homebrew/bin` and
   `/usr/local/bin` on macOS (a Finder-launched app has a minimal PATH), first one that
   reports version 3.10 or newer. Older interpreters (such as the macOS 3.9 stub) are
   skipped, and `/usr/bin/python3` is not touched on macOS when the Command Line Tools are
   missing, because running it opens an installer dialog.
3. **None**: `detect()` returns `None` and the Python tab is greyed out, as with bash or
   PowerShell when those are missing.

The POSIX rlimit shim also needs a Python; when frozen it uses the same detected runtime.

`tools/fetch_runtime.py` options: `--force` (replace), `--full` (skip pruning),
`--target TRIPLE` (for example `x86_64-apple-darwin`, to package for another arch),
`--release TAG` (pin a python-build-standalone release instead of the latest).
Supported targets: `aarch64-apple-darwin`, `x86_64-apple-darwin`, `x86_64-pc-windows-msvc`,
`x86_64-unknown-linux-gnu`.

## Not a security boundary

The bundled interpreter changes nothing about safety. Player code still runs as a local
subprocess, as the player, with a timeout, a temp directory, a scrubbed environment and
output limits (plus rlimits on POSIX). This guards against accidents like infinite loops.
It is **not** a sandbox against hostile code; see "Player code and safety" in the README.
Do not ship features that run code the player did not write (for example, shared puzzle
solutions downloaded from the internet) without a real isolation layer.

## Release workflow

`.github/workflows/release.yml` runs on a pushed `v*` tag (or by hand via
`workflow_dispatch`, which builds and uploads workflow artifacts only). A matrix of
`macos-14` (arm64), `windows-latest` (x64) and `ubuntu-22.04` (x64) installs the game with
Python 3.13, fetches assets and the runtime, builds, smoke-tests the build with `--doctor`
and `--headless-frames 60 --new`, and zips it as `CodeRogue-<os>-<arch>.zip` (`ditto -c -k
--keepParent` for the `.app`, so the bundle's symlinks survive). A final job attaches every
zip to a **draft** GitHub release; publish it by hand after checking the downloads.

There is no Intel macOS build yet. Add a `macos-13` matrix entry (x86_64), or build a
universal2 app later.

## TODO: signing and notarization

Release builds are unsigned (macOS: ad-hoc only). Users will see Gatekeeper ("cannot be
opened because the developer cannot be verified"; right-click > Open works) and Windows
SmartScreen warnings. To fix:

### macOS

1. Join the Apple Developer Program and create a **Developer ID Application** certificate.
   Export it as a `.p12` and store it, its password, the Apple ID, the team ID and an
   app-specific password as GitHub secrets.
2. In CI, import it into a temporary keychain (`security create-keychain`,
   `security import cert.p12 -k build.keychain -P "$P12_PASSWORD" -T /usr/bin/codesign`,
   `security set-key-partition-list -S apple-tool:,apple: -k "$KEYCHAIN_PW" build.keychain`).
3. Sign inside-out with the hardened runtime and a timestamp. The bundled interpreter needs
   entitlements for a Python that loads extension modules:
   `com.apple.security.cs.allow-unsigned-executable-memory` and
   `com.apple.security.cs.disable-library-validation` in `entitlements.plist`.
   ```sh
   codesign --force --deep --options runtime --timestamp \
     --entitlements entitlements.plist \
     --sign "Developer ID Application: <Name> (<TEAMID>)" dist/CodeRogue.app
   codesign --verify --deep --strict --verbose=2 dist/CodeRogue.app
   ```
   If `--deep` misses nested binaries in `Contents/Resources/runtime`, sign every Mach-O
   there first (`find ... -type f -perm +111` plus `*.dylib` and `*.so`), then the app.
4. Notarize and staple:
   ```sh
   ditto -c -k --keepParent dist/CodeRogue.app CodeRogue-notarize.zip
   xcrun notarytool submit CodeRogue-notarize.zip --apple-id "$APPLE_ID" \
     --team-id "$TEAM_ID" --password "$APP_SPECIFIC_PASSWORD" --wait
   xcrun stapler staple dist/CodeRogue.app
   spctl --assess --type execute --verbose dist/CodeRogue.app
   ```
5. Re-zip the stapled app for the release asset.

### Windows

Sign `CodeRogue.exe` (and ideally `runtime\python\python.exe`) with an Authenticode
certificate (OV/EV, or Azure Trusted Signing) using `signtool sign /fd SHA256 /tr
<timestamp-url> /td SHA256 ...`. SmartScreen reputation builds over downloads; EV or Trusted
Signing gets it faster.

## Steam notes

- **Depots per OS.** One depot each for Windows, macOS and Linux, each containing the
  unzipped build for that OS (the `.app` for macOS). Launch options: `CodeRogue.exe`,
  `CodeRogue.app`, `CodeRogue`. Shared content is small (under 10 MB), so a shared depot is
  not worth it.
- **Steam Linux Runtime.** Set the Linux launch to run under Steam Linux Runtime 3.0
  (sniper). A PyInstaller build only runs on a glibc at least as new as the build machine's,
  and sniper is Debian 11 (glibc 2.31) while `ubuntu-22.04` has glibc 2.35. Before shipping
  on Steam, build the Linux depot inside the sniper SDK image
  (`registry.gitlab.steamos.cloud/steamrt/sniper/sdk`) or another glibc 2.31 base.
  The bundled python-build-standalone runtime needs glibc 2.17, so it is not the limit.
  The `unshare -rn` network cut may be unavailable inside the container; the sandbox already
  falls back to running without it.
- **Steam Deck.** The game is about typing code with VIM keys. The Deck's on-screen keyboard
  (Steam + X) works for short edits but is a poor fit for writing programs, and Steam Input
  must not map keyboard keys in a way that eats `Esc` or `:`. Recommend a physical keyboard;
  expect "Playable" at best, not "Verified". bash is present on SteamOS; PowerShell is not.
- **Saves and Steam Cloud.** Point Steam Auto-Cloud at the per-user data dir (see
  `coderogue/save/store.py`), never at the install folder.
- **Overlay on macOS** needs a signed build; see the signing TODO.

## Verification status

Verified on macOS 27 arm64 (Python 3.14.8, PyInstaller 6.22.3): build, `--doctor`,
`--headless-frames 60 --new` from inside the `.app`, a 3 second windowed launch, and the
fallback chain (runtime removed: Homebrew `python3` found; also with `PATH=/usr/bin:/bin`,
where the 3.9 `/usr/bin/python3` is skipped). Windows and Linux builds and the release
workflow have not been run yet; the first tagged build (or a `workflow_dispatch` run) is
their test.
