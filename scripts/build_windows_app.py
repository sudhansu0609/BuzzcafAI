"""Buzzcaf Studio Windows App & Installer Builder.

Compiles the native Windows executable (`Buzzcaf Studio.exe`) and the
Setup Wizard (`installer/Buzzcaf Studio Setup.exe`) directly using Windows
native toolchain.
"""

import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(ROOT_DIR, "assets")
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
INSTALLER_DIR = os.path.join(ROOT_DIR, "installer")
CSC_EXE = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def step_1_generate_icons():
    print("[1/4] Generating high-resolution application icons...")
    from generate_icon import create_buzzcaf_icon

    icon_path = os.path.join(ASSETS_DIR, "buzzcaf_studio.ico")
    create_buzzcaf_icon(icon_path)
    if not os.path.isfile(icon_path):
        raise RuntimeError(f"Failed to generate icon at {icon_path}")
    print(f"      [OK] Icon created: {icon_path}")
    return icon_path


def step_2_build_launcher(icon_path: str):
    print("\n[2/4] Compiling native desktop executable: 'Buzzcaf Studio.exe'...")
    launcher_src = os.path.join(SCRIPTS_DIR, "launcher", "Launcher.cs")
    manifest = os.path.join(SCRIPTS_DIR, "launcher", "app.manifest")
    out_exe = os.path.join(ROOT_DIR, "Buzzcaf Studio.exe")

    cmd = [
        CSC_EXE,
        "/target:winexe",
        f"/win32icon:{icon_path}",
        f"/win32manifest:{manifest}",
        f"/out:{out_exe}",
        "/r:System.dll,System.Windows.Forms.dll,System.Drawing.dll",
        launcher_src,
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Compilation Error:\n", res.stdout, res.stderr)
        raise RuntimeError("Failed to compile Buzzcaf Studio.exe")

    print(f"      [OK] Application compiled: {out_exe} ({os.path.getsize(out_exe):,} bytes)")
    return out_exe


def step_3_build_installer(icon_path: str):
    print("\n[3/4] Compiling Windows Setup Wizard: 'installer/Buzzcaf Studio Setup.exe'...")
    installer_src = os.path.join(SCRIPTS_DIR, "installer", "Installer.cs")
    manifest = os.path.join(SCRIPTS_DIR, "launcher", "app.manifest")
    out_exe = os.path.join(INSTALLER_DIR, "Buzzcaf Studio Setup.exe")

    cmd = [
        CSC_EXE,
        "/target:winexe",
        f"/win32icon:{icon_path}",
        f"/win32manifest:{manifest}",
        f"/out:{out_exe}",
        "/r:System.dll,System.Windows.Forms.dll,System.Drawing.dll",
        installer_src,
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Compilation Error:\n", res.stdout, res.stderr)
        raise RuntimeError("Failed to compile Buzzcaf Studio Setup.exe")

    print(f"      [OK] Installer compiled: {out_exe} ({os.path.getsize(out_exe):,} bytes)")
    return out_exe


def step_4_build_uninstaller(icon_path: str):
    print("\n[4/4] Compiling Uninstaller: 'Uninstall Buzzcaf Studio.exe'...")
    uninstaller_src = os.path.join(SCRIPTS_DIR, "installer", "Uninstaller.cs")
    manifest = os.path.join(SCRIPTS_DIR, "launcher", "app.manifest")
    out_exe = os.path.join(INSTALLER_DIR, "Uninstall Buzzcaf Studio.exe")

    cmd = [
        CSC_EXE,
        "/target:winexe",
        f"/win32icon:{icon_path}",
        f"/win32manifest:{manifest}",
        f"/out:{out_exe}",
        "/r:System.dll,System.Windows.Forms.dll,System.Drawing.dll",
        uninstaller_src,
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Compilation Error:\n", res.stdout, res.stderr)
        raise RuntimeError("Failed to compile Uninstall Buzzcaf Studio.exe")

    # Copy to root as well
    root_uninst = os.path.join(ROOT_DIR, "Uninstall Buzzcaf Studio.exe")
    import shutil

    shutil.copy2(out_exe, root_uninst)
    print(f"      [OK] Uninstaller compiled: {root_uninst} ({os.path.getsize(root_uninst):,} bytes)")
    return root_uninst


def main():
    print("=" * 60)
    print(" Buzzcaf Studio - Windows Native Build System")
    print("=" * 60)

    if not os.path.isfile(CSC_EXE):
        sys.exit(f"Error: C# compiler not found at {CSC_EXE}")

    os.chdir(SCRIPTS_DIR)
    icon_path = step_1_generate_icons()
    step_2_build_launcher(icon_path)
    step_3_build_installer(icon_path)
    step_4_build_uninstaller(icon_path)

    print("\n" + "=" * 60)
    print(" BUILD COMPLETE!")
    print(" Outputs:")
    print(f"  * Application: {os.path.join(ROOT_DIR, 'Buzzcaf Studio.exe')}")
    print(f"  * Installer:   {os.path.join(INSTALLER_DIR, 'Buzzcaf Studio Setup.exe')}")
    print(f"  * Uninstaller: {os.path.join(ROOT_DIR, 'Uninstall Buzzcaf Studio.exe')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
