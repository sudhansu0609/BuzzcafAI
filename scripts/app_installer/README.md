# App installer template

The setup wizard every Buzzcaf Media desktop app ships (BuzzEdit, BuzzAnimate, MastGaane, VrDeep,
SmartCleaner, BuzzViolin, buzzBooks). Each app keeps its own copy in `<app>\installer\`; this
folder is the master. It installs an app **in place**, the way `Buzzcaf Studio Setup.exe` does:
nothing is copied to Program Files, the app runs from its own folder, and the wizard

1. (re)builds the app's environment by running `installer\setup_env.ps1` (venvs, CUDA PyTorch,
   `node_modules`, a Rust build...) with its output in the wizard and in `logs\setup.log`;
2. makes the Desktop shortcut and the Start Menu one under **Buzzcaf Media**, plus "Uninstall";
3. registers the app in **Settings > Apps** (`HKCU\...\Uninstall\Buzzcaf.<id>`; "Modify" re-runs Setup);
4. writes `installer\installed.json`, the marker that tells SmartCleaner never to offer this app's
   environments for cleanup (SmartCleaner also protects every registered app's InstallLocation).

Running Setup again repairs an install: every step of `setup_env.ps1` skips what is already in
place, so it finishes a setup that stopped and rebuilds only what is missing. `Uninstall <Name>.exe`
removes the shortcuts, the Apps entry and the marker, and never deletes the folder, data, models
or environments. Both take `/quiet` (no dialogs; used by tests and scripts). A quiet Setup does
not start the app afterwards unless `/launch` is given too. From Git Bash, which rewrites a bare
`/quiet` into a path, use `--quiet` / `--launch`.

**One setup per app at a time.** `setup_common.ps1` writes `installer\setup.running` (the PID of
the powershell running it) and removes it when the script ends through `Done` or `Fail`. A second
setup of the same app -- the wizard, the app's own launcher repairing itself, the Studio's Health
page auto-repair -- waits for the first (up to an hour), then runs and finds its work done. A lock
whose PID is gone is stale and is taken over. Keep `installer/setup.running` in `.gitignore`.

**Self-repair.** The Studio's Health page checks each installed app's `health_paths` (in its
`app.json`) and runs `setup_env.ps1` when one is missing; BuzzEdit's `START_APP.ps1` runs its
Setup itself before starting when its environments are missing.

**Self-test: works, not only exists (2026-10-26).** Files being there is not enough: after the
SmartCleaner wipe BuzzEdit's rebuilt `.venv` had every `health_paths` file, but Whisper could not
load cuBLAS and hung a production for 9 hours. An app declares a self-test in `app.json`:

```json
"self_test": {"python": ".venv\\Scripts\\python.exe", "script": "installer\\selftest.py",
              "result": "installer\\selftest.json", "timeout_s": 240}
```

(`python` is a path in the app or a command on PATH, e.g. `"node"` with a `.mjs` script.) The script
checks that each part actually runs -- for BuzzEdit: Whisper's CUDA libraries load before torch is
imported, torch sees the GPU, the backend app loads, the narration and voice engines start -- writes
`selftest.json` (`{ok, at, checks: [{name, ok, required, detail}]}`) and exits 0 only when every
required check passes. It is run by `setup_env.ps1` as its last step (a setup that does not pass is
not finished, and tries its known remedy first), by the app's launcher before starting (a recent
pass newer than the last package change is trusted), and by the Studio: a failed result makes the
Health row fail and starts the repair, the nightly run calls `app_envs.ensure_working` (test ->
repair -> test) for every app the night needs, and Tonight's run lists it with a Fix button.

The Studio's service apps (`claudeAPI`, `geminiApi`, `searxng`) carry the same `installer\` without
a wizard (`"service": true`): the Studio starts them, so they need the repair, the self-test and the
`installed.json` marker that keeps SmartCleaner away, not shortcuts.

Apps that already had their own installer keep it and gain the same `installer\` repair, self-test
and marker (`"own_installer"` in `app.json` names it):

- **Dexter** (`Dexter-Setup.exe`): runs on the system Python 3.14. `setup_env.ps1` installs any
  package in `requirements.txt` that is missing (one at a time, only the window's core is fatal),
  caches the MiniLM embedding model, restores `node_modules`, rebuilds `dist` when missing or older
  than `src`, rebuilds `Dexter.exe`, then self-tests (the launch preflight, every requirement, the
  bundle, the launcher, the clone_env and kokoro_gpu sidecars). `backend\desktop_app.py` runs it by
  itself when the launch preflight fails, and checks again before showing the error dialog.
- **Sentinel** (`sentinel-installer.exe`, `install.ps1`): lives in `C:\Program Files\Sentinel` as
  a service only an Administrator can install, start or replace. The self-test is read-only
  (binaries, service automatic and running, `\\.\pipe\Sentinel`, `--verify` on the live config,
  the tray); the repair starts the tray, reinstalls a missing service when elevated, and otherwise
  fails with the command to run. The nightly run self-tests it with the other apps the night needs.

`Ensure-NodeModules` decides by whether the packages resolve (`npm ls`), never by timestamps: a
needless `npm ci` deletes `node_modules` first, and with the app running Windows refuses half the
deletes and leaves it without packages.

**Pitfalls in Windows PowerShell 5.1** (all handled in `setup_common.ps1`; keep them in mind in
an app's own `setup_env.ps1`): under `$ErrorActionPreference = "Stop"` any stderr from a native
command -- even with `2>$null` -- is a terminating error, so run probes with `Test-Native` and
real work with `Invoke-Native`, never a bare `& exe ... 2>$null`; a one-element list returned from
an `if` collapses to a scalar, so wrap such expressions in `@(...)` before using `+`.

| File | What |
|---|---|
| `Setup.cs` | the wizard (WinForms, .NET Framework, C# 5) |
| `Uninstall.cs` | the uninstaller (compiled together with `Setup.cs` for its shared paths) |
| `setup_common.ps1` | helpers for `setup_env.ps1`: `Set-Steps`/`Step` (progress), `Ensure-Venv` (uv when present), `Pip-Install`, `Pip-Requirements`, `Ensure-CudaTorch` (cu128, for the Blackwell 5060 Ti), `Ensure-NodeModules`, `Invoke-Native`, `Require-Command`, `Find-Python`, `Fail`, `Done` |
| `build_installer.ps1` | reads `installer\app.json`, generates `AppInfo.cs`, compiles `installer\<Name> Setup.exe` and `installer\Uninstall <Name>.exe` with the csc that ships with Windows |

## Adding the installer to an app

1. Copy the four files above into `<app>\installer\`.
2. Write `installer\app.json`:

   ```json
   {
     "id": "BuzzEdit",
     "name": "BuzzEdit",
     "description": "one line shown under the name",
     "version": "1.0.0",
     "launch_target": "%WINDIR%\\System32\\wscript.exe",
     "launch_args": "\"{root}\\START_APP.vbs\"",
     "icon": "build\\icon.ico",
     "setup_script": "installer\\setup_env.ps1",
     "env_summary": "what step 1 installs, shown on the checkbox",
     "estimated_mb": 25000
   }
   ```

   `{root}` is the app's folder; environment variables expand. The shortcut must start the app
   without a console window (a `.vbs`, `pythonw`, or the app's own exe).
3. Write `installer\setup_env.ps1`: dot-source `setup_common.ps1`, `Set-Steps <n>`, then one
   `Step "..."` per stage, each one idempotent. `BuzzEdit\installer\setup_env.ps1` is the worked example.
4. `powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1`, then test with
   `"installer\<Name> Setup.exe" /quiet` and `"installer\Uninstall <Name>.exe" /quiet`.
5. Add `installer/installed.json` and `logs/` to the app's `.gitignore`; add an "Install" section to
   its README.

When the template changes, copy the changed file into every app's `installer\` and rebuild.
