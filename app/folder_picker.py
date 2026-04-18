from __future__ import annotations

import threading


def _show_dialog(initial: str | None) -> str | None:
    """Invoke tkinter.filedialog.askdirectory in a hidden-root context.

    Raises ImportError if tkinter is not available (e.g. headless CI).
    Returns the chosen absolute path, or None if the user cancelled.
    """
    import tkinter  # noqa: F401  # raise ImportError early if missing
    from tkinter import Tk, filedialog

    root = Tk()
    try:
        root.withdraw()  # hide the empty root window
        root.attributes("-topmost", True)  # bring the dialog forward on macOS
        chosen = filedialog.askdirectory(initialdir=initial or "")
        return chosen or None
    finally:
        root.destroy()


def pick_folder(initial: str | None = None) -> str | None:
    """Open a native folder picker and return the chosen absolute path.

    Runs the dialog in a worker thread so a blocking call in an async
    web handler doesn't starve the event loop. Returns None if the user
    cancels or tkinter is unavailable.
    """
    result: dict[str, str | None] = {"path": None}
    error: dict[str, BaseException | None] = {"err": None}

    def target():
        try:
            result["path"] = _show_dialog(initial)
        except Exception as e:  # pragma: no cover — production-only path
            error["err"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join()

    if error["err"] is not None:
        return None
    return result["path"]
