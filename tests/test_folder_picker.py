from app import folder_picker


def test_pick_folder_returns_stub_path(monkeypatch):
    monkeypatch.setattr(folder_picker, "_show_dialog",
                        lambda initial: "/Users/me/Movies")
    assert folder_picker.pick_folder() == "/Users/me/Movies"


def test_pick_folder_returns_none_when_cancelled(monkeypatch):
    monkeypatch.setattr(folder_picker, "_show_dialog", lambda initial: None)
    assert folder_picker.pick_folder() is None


def test_pick_folder_returns_none_when_tkinter_missing(monkeypatch):
    def raise_import(initial):
        raise ImportError("no tkinter")
    monkeypatch.setattr(folder_picker, "_show_dialog", raise_import)
    assert folder_picker.pick_folder() is None


def test_pick_folder_passes_initial_through(monkeypatch):
    captured = {}

    def fake(initial):
        captured["initial"] = initial
        return "/Users/me"

    monkeypatch.setattr(folder_picker, "_show_dialog", fake)
    folder_picker.pick_folder("/Users/me/Movies")
    assert captured["initial"] == "/Users/me/Movies"
