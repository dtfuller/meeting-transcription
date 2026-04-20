from __future__ import annotations

import platform
import subprocess


def _show_dialog(initial: str | None) -> str | None:
    """Open a native folder picker and return the chosen POSIX path.

    macOS: uses AppleScript (``osascript``) so the dialog runs in a fresh
    subprocess with its own main thread. tkinter's ``Tk()`` on a non-main
    thread is silently broken on macOS, so we avoid it entirely.

    Other platforms: returns None today. Plug a tkinter fallback in here if
    the app ever runs on Linux/Windows.
    """
    if platform.system() != "Darwin":
        return None

    initial_clause = (
        f' default location (POSIX file "{initial}" as alias)' if initial else ""
    )
    script = (
        'tell application "System Events" to activate\n'
        "try\n"
        f'  set chosen to choose folder with prompt "Select watch directory"{initial_clause}\n'
        "  return POSIX path of chosen\n"
        "on error\n"
        '  return ""\n'
        "end try\n"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    path = (result.stdout or "").strip()
    return path or None


def pick_folder(initial: str | None = None) -> str | None:
    """Open the native folder picker. Returns the chosen path or None."""
    try:
        return _show_dialog(initial)
    except Exception:
        return None
