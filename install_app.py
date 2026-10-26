#!/usr/bin/env python3
"""
Turns Desktop Puppy into a real Windows app.

    python install_app.py              build DesktopPuppy.exe, install it, add Start Menu + Desktop
                                       shortcuts, and make it start automatically when you sign in
    python install_app.py --no-startup same, but do not start it at sign-in
    python install_app.py --uninstall  close it and remove the app, shortcuts and auto-start

After installing:
  * It starts by itself every time you sign in to Windows.
  * Open it any time from the Start Menu or Desktop ("Desktop Puppy"); if it is already running
    nothing happens (there is only ever one puppy).
  * Close it by right-clicking the kennel.
"""

import base64
import io
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "Desktop Puppy"
EXE = "DesktopPuppy.exe"
INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "DesktopPuppy")


def ps(script):
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True)


def folders():
    r = ps("[Environment]::GetFolderPath('Startup'); [Environment]::GetFolderPath('Programs'); "
           "[Environment]::GetFolderPath('Desktop')")
    startup, programs, desktop = [x.strip() for x in r.stdout.strip().splitlines()[:3]]
    return startup, programs, desktop


def make_icon(path):
    """puppy.ico from the standing sprite."""
    try:
        from PIL import Image
        sys.path.insert(0, HERE)
        import puppy_sprites as spr
        ox, oy, w, h, b64 = spr.FRAMES["stand0"]
        im = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
        side = max(w, h) + 4
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(im, ((side - w) // 2, (side - h) // 2), im)
        sq = sq.resize((256, 256), Image.NEAREST)
        sq.save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return True
    except Exception as e:
        print("  (no icon:", e, ")")
        return False


def build():
    work = os.path.join(HERE, "build_app")
    icon = os.path.join(work, "puppy.ico")
    os.makedirs(work, exist_ok=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
            "--name", "DesktopPuppy", "--distpath", os.path.join(work, "dist"),
            "--workpath", os.path.join(work, "tmp"), "--specpath", work,
            "--paths", HERE]
    if make_icon(icon):
        args += ["--icon", icon]
    args.append(os.path.join(HERE, "desktop_puppy.py"))
    print("Building", EXE, "(this takes a minute)...")
    if subprocess.run(args).returncode != 0:
        sys.exit("Build failed - is PyInstaller installed?  python -m pip install pyinstaller")
    return os.path.join(work, "dist", EXE)


def shortcut(path, target):
    ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{path}');"
       f"$s.TargetPath='{target}';$s.WorkingDirectory='{os.path.dirname(target)}';"
       f"$s.IconLocation='{target},0';$s.Description='A puppy that lives on your desktop';$s.Save()")


def stop():
    subprocess.run(["taskkill", "/F", "/IM", EXE], capture_output=True)


def install(startup_on):
    exe = build()
    stop()
    os.makedirs(INSTALL_DIR, exist_ok=True)
    target = os.path.join(INSTALL_DIR, EXE)
    shutil.copy2(exe, target)
    startup, programs, desktop = folders()
    shortcut(os.path.join(programs, NAME + ".lnk"), target)
    shortcut(os.path.join(desktop, NAME + ".lnk"), target)
    lnk = os.path.join(startup, NAME + ".lnk")
    if startup_on:
        shortcut(lnk, target)
    elif os.path.exists(lnk):
        os.remove(lnk)
    print(f"\nInstalled to {INSTALL_DIR}")
    print("  Start Menu + Desktop shortcut:", NAME)
    print("  Starts automatically at sign-in:", "yes" if startup_on else "no")
    subprocess.Popen([target], cwd=INSTALL_DIR)
    print("Puppy is on its way! Right-click the kennel to close it.")


def uninstall():
    stop()
    startup, programs, desktop = folders()
    for d in (startup, programs, desktop):
        p = os.path.join(d, NAME + ".lnk")
        if os.path.exists(p):
            os.remove(p)
    shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    print("Desktop Puppy removed (its saved kennel position ~/.desktop_puppy.json was left alone).")


if __name__ == "__main__":
    if not sys.platform.startswith("win"):
        sys.exit("This installer is for Windows.")
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install("--no-startup" not in sys.argv)
