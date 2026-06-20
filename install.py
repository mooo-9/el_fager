"""
El Fager installer — creates Desktop + Start Menu shortcuts.
Run once: python install.py
"""

import os
import subprocess
import sys
from pathlib import Path


def _generate_icon(ico_path: Path) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 252, 252], fill=(10, 10, 15, 255))
    draw.ellipse([20, 20, 236, 236], fill=(100, 200, 255, 255))
    draw.ellipse([50, 50, 206, 206], fill=(10, 10, 15, 255))
    draw.ellipse([100, 100, 156, 156], fill=(100, 200, 255, 255))
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(ico_path), format="ICO", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
    print(f"  Icon saved: {ico_path}")


def _create_shortcut(lnk_path: Path, target: str, args: str, working_dir: str, icon: str) -> None:
    ps = f"""
$s = (New-Object -COM WScript.Shell).CreateShortcut('{lnk_path}')
$s.TargetPath  = '{target}'
$s.Arguments   = '{args}'
$s.WorkingDirectory = '{working_dir}'
$s.IconLocation = '{icon}'
$s.Description = 'El Fager AI Assistant'
$s.Save()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  Shortcut created: {lnk_path}")
    else:
        print(f"  Failed: {result.stderr.strip()}")


def main():
    here = Path(__file__).resolve().parent
    ico  = here / "data" / "el_fager.ico"

    if not ico.exists():
        print("Generating icon...")
        _generate_icon(ico)

    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    main_py   = str(here / "main.py")
    work_dir  = str(here)
    icon_str  = str(ico)
    target    = str(pythonw)
    args      = f'"{main_py}"'

    # Desktop shortcut — resolve the real Desktop path via PowerShell
    _desktop_raw = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True
    ).stdout.strip()
    desktop = Path(_desktop_raw) / "El Fager.lnk" if _desktop_raw else None
    if desktop:
        print("Creating Desktop shortcut...")
        _create_shortcut(desktop, target, args, work_dir, icon_str)
    else:
        print("  Could not resolve Desktop path — skipping.")

    # Start Menu shortcut
    start_menu = (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft" / "Windows" / "Start Menu"
        / "Programs" / "El Fager.lnk"
    )
    print("Creating Start Menu shortcut...")
    _create_shortcut(start_menu, target, args, work_dir, icon_str)

    print("\nDone! El Fager is now on your Desktop and in the Start Menu.")
    print("You can also pin 'El Fager' from the Start Menu to your Taskbar.")


if __name__ == "__main__":
    main()
