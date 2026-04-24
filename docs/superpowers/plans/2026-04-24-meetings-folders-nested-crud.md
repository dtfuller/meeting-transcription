# Nested Folder CRUD + Drag-and-Drop Moves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create, rename, delete, and rearrange nested folders in the `/meetings` left tree from the UI — with drag-and-drop for moves — while widening `Meeting.subdir` to support full relative paths (e.g. `Clients/Acme/Q1`) and collapsing meeting URLs to stem-only (`/meetings/{stem}`). Per the approved plan at `/Users/davidfuller/.claude/plans/let-s-plan-i-want-optimized-gray.md`.

**Architecture:** Filesystem is the source of truth — every real directory under `data/` is a folder; `transcripts/` and `information/` mirror it. No new DB tables. Two pure helper modules (`app/folders.py` for validation, new functions in `app/fs.py` for folder I/O and atomic moves) keep the logic testable without hitting HTTP. Folder CRUD + move are HTMX-friendly POSTs that return the refreshed `<aside class="tree">` partial. Drag-and-drop is ~60 lines of vanilla JS that synthesizes the POST and asks HTMX to repaint; all rules live server-side.

**Tech Stack:** Python 3.11 · FastAPI · Jinja2 · HTMX · vanilla JS (HTML5 DnD API) · pytest.

---

## File structure

**New files:**

```
app/
  folders.py              # validate_folder_name, validate_folder_path
  routes/
    folders.py            # CRUD + move handlers
static/
  tree_dnd.js             # drag-and-drop handlers
tests/
  test_fs_folders.py      # all fs.py folder + move helpers
  test_folders_validation.py
  test_routes_folders.py
  test_stem_uniqueness_warning.py
```

**Modified:**

- `app/fs.py` — widen `Meeting.subdir`; add `Folder`, `TreeNode`, `list_folders`, `folder_exists`, `folder_is_empty`, `build_tree`, `find_meeting_by_stem`, `move_meeting_artifacts`, `move_folder_tree`, `assert_stem_uniqueness_or_warn`.
- `app/routes/meetings.py` — stem-only URLs; add `POST /meetings/{stem}/move`; add `GET /meetings/tree-partial`.
- `app/routes/inbox.py` — replace hand-rolled 4-path move loop with `fs.move_meeting_artifacts`; replace hand-rolled target_subdir validation with `folders.validate_folder_path`; broaden datalist to full folder paths.
- `app/routes/media.py` — stem-only video URL.
- `app/routes/search_routes.py` — stem-only deep links.
- `server.py` — register `app/routes/folders.py` router; call `fs.assert_stem_uniqueness_or_warn()` on startup.
- `templates/_meeting_tree.html` — rewrite as recursive Jinja macro with hover actions, drop targets, tree banner.
- `templates/_meeting_detail.html` — subdir becomes display-only breadcrumb; action form URLs drop the `{subdir}` segment.
- `templates/base.html` — include `static/tree_dnd.js`.
- `static/app.css` — new `.tree-*` rules (~50 lines).
- `tests/test_routes_meetings.py` — rewrite all `/meetings/{subdir}/{stem}*` calls to `/meetings/{stem}*`; add nested-subdir resolution tests.
- `tests/test_routes_inbox.py` — one new spy test on the new move helper.
- `tests/test_group_meetings.py` — one new nested-tree test.
- `tests/helpers/sample_assets.py` — extend to seed a nested fixture.

---

## Task 1: Widen `Meeting.subdir` to full relative parent path + add `find_meeting_by_stem`

**Files:**
- Modify: `app/fs.py`
- Test: `tests/test_fs_folders.py` (new)
- Modify: `tests/helpers/sample_assets.py`

- [ ] **Step 1: Extend `build_sample_tree` to seed one nested meeting**

Add at the end of `tests/helpers/sample_assets.py`:

```python
def build_nested_sample_tree(root: Path) -> None:
    """Builds on build_sample_tree with a 2-deep nested meeting."""
    build_sample_tree(root)
    data = root / "data" / "Clients" / "Acme"
    transcripts = root / "transcripts" / "Clients" / "Acme"
    information = root / "information" / "Clients" / "Acme"
    data.mkdir(parents=True, exist_ok=True)
    (data / "2026-04-20 09-00-00.mov").write_bytes(b"\x00" * 16)
    write(transcripts / "2026-04-20 09-00-00.txt",
          "[00:00:00 Alice] hello from Acme\n")
    write(information / "2026-04-20 09-00-00-knowledge.md", "# K\n")
    write(information / "2026-04-20 09-00-00-commitments.md", "# C\n")
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_fs_folders.py`:

```python
import pytest

from app import fs
from tests.helpers.sample_assets import build_nested_sample_tree, build_sample_tree


@pytest.fixture
def nested_tree(tmp_path, monkeypatch):
    build_nested_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    return tmp_path


def test_meeting_subdir_preserves_full_nested_path(nested_tree):
    meetings = {m.stem: m for m in fs.list_meetings()}
    nested = meetings["2026-04-20 09-00-00"]
    assert nested.subdir == "Clients/Acme"


def test_meeting_subdir_empty_string_for_root_level(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    # Seed a root-level .mov (no subdir).
    (tmp_path / "data" / "rootcast.mov").write_bytes(b"\x00" * 16)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    meetings = {m.stem: m for m in fs.list_meetings()}
    assert meetings["rootcast"].subdir == ""


def test_meeting_transcript_path_uses_nested_subdir(nested_tree):
    meetings = {m.stem: m for m in fs.list_meetings()}
    nested = meetings["2026-04-20 09-00-00"]
    assert nested.transcript_path == (
        nested_tree / "transcripts" / "Clients" / "Acme" / "2026-04-20 09-00-00.txt"
    )


def test_find_meeting_by_stem_resolves_nested(nested_tree):
    m = fs.find_meeting_by_stem("2026-04-20 09-00-00")
    assert m is not None
    assert m.subdir == "Clients/Acme"


def test_find_meeting_by_stem_returns_none_when_missing(nested_tree):
    assert fs.find_meeting_by_stem("does-not-exist") is None
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_fs_folders.py -v
```

Expected: all 5 fail — either `AttributeError` on `find_meeting_by_stem`, or subdir assertion mismatch.

- [ ] **Step 4: Widen `_meeting_from_mov`**

In `app/fs.py`, replace the body of `_meeting_from_mov` (currently ~lines 62-74):

```python
def _meeting_from_mov(mov: Path) -> Meeting:
    rel = mov.relative_to(DATA_DIR)
    subdir = str(rel.parent) if rel.parent != Path(".") else ""
    stem = mov.stem
    base = Path(subdir) / stem
    return Meeting(
        subdir=subdir,
        stem=stem,
        mov_path=mov,
        transcript_path=(TRANSCRIPTS_DIR / base).with_suffix(".txt"),
        knowledge_path=INFORMATION_DIR / subdir / f"{stem}-knowledge.md",
        commitments_path=INFORMATION_DIR / subdir / f"{stem}-commitments.md",
    )
```

- [ ] **Step 5: Add `find_meeting_by_stem`**

In `app/fs.py`, add below `find_meeting`:

```python
def find_meeting_by_stem(stem: str) -> Meeting | None:
    for m in list_meetings(include_inbox=True):
        if m.stem == stem:
            return m
    return None
```

- [ ] **Step 6: Run tests to verify they pass**

```
pytest tests/test_fs_folders.py -v
```

Expected: 5 PASS.

- [ ] **Step 7: Run full suite to confirm no regressions**

```
pytest -q
```

Expected: 194 passing → still 194 passing (new tests add 5, so ~199). Fix anything that fell over.

- [ ] **Step 8: Commit**

```
git add app/fs.py tests/test_fs_folders.py tests/helpers/sample_assets.py
git commit -m "feat(fs): widen Meeting.subdir to full relative path + find_meeting_by_stem"
```

---

## Task 2: `Folder` dataclass + `list_folders` + `folder_exists` + `folder_is_empty`

**Files:**
- Modify: `app/fs.py`
- Test: `tests/test_fs_folders.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_fs_folders.py`:

```python
def test_list_folders_walks_all_depths(nested_tree):
    folders = {f.path: f for f in fs.list_folders()}
    assert "Clients" in folders
    assert "Clients/Acme" in folders
    assert folders["Clients/Acme"].name == "Acme"
    assert folders["Clients/Acme"].parent == "Clients"
    assert folders["Clients"].parent == ""


def test_list_folders_excludes_inbox(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    inbox = tmp_path / "data" / "_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "pending.mov").write_bytes(b"\x00")
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    paths = [f.path for f in fs.list_folders()]
    assert "_inbox" not in paths


def test_folder_exists_for_existing_and_missing(nested_tree):
    assert fs.folder_exists("Clients") is True
    assert fs.folder_exists("Clients/Acme") is True
    assert fs.folder_exists("nope") is False
    # Root "" is always considered existing.
    assert fs.folder_exists("") is True


def test_folder_is_empty_false_when_meeting_present(nested_tree):
    # "Clients" contains "Acme" which contains a meeting.
    assert fs.folder_is_empty("Clients") is False


def test_folder_is_empty_true_for_empty_dir(tmp_path, monkeypatch):
    (tmp_path / "data" / "Empty").mkdir(parents=True)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    assert fs.folder_is_empty("Empty") is True


def test_folder_is_empty_false_when_only_subfolder_present(tmp_path, monkeypatch):
    (tmp_path / "data" / "Parent" / "Child").mkdir(parents=True)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    assert fs.folder_is_empty("Parent") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_fs_folders.py -v
```

Expected: new tests fail — `AttributeError` on `list_folders`, `folder_exists`, `folder_is_empty`.

- [ ] **Step 3: Implement the new helpers**

In `app/fs.py`, below the `Clip` dataclass, add:

```python
@dataclass(frozen=True)
class Folder:
    path: str   # ""=root, "Clients", "Clients/Acme"
    name: str   # leaf name ("Acme"); "" for root
    parent: str # parent path ("" for top-level folders)


def list_folders() -> list[Folder]:
    """Every directory under DATA_DIR that is not _inbox or inside _inbox."""
    if not DATA_DIR.exists():
        return []
    folders: list[Folder] = []
    for p in sorted(DATA_DIR.rglob("*")):
        if not p.is_dir():
            continue
        rel = p.relative_to(DATA_DIR)
        if rel.parts and rel.parts[0] == "_inbox":
            continue
        folders.append(Folder(
            path=str(rel),
            name=rel.name,
            parent=str(rel.parent) if rel.parent != Path(".") else "",
        ))
    return folders


def folder_exists(path: str) -> bool:
    """Root ('') is always considered to exist."""
    if not path:
        return True
    return (DATA_DIR / path).is_dir()


def folder_is_empty(path: str) -> bool:
    """True when there are no subfolders (excluding _inbox) and no .mov files
    anywhere beneath `path`. A missing directory is considered empty."""
    root = (DATA_DIR / path) if path else DATA_DIR
    if not root.is_dir():
        return True
    for p in root.rglob("*"):
        rel = p.relative_to(DATA_DIR)
        if rel.parts and rel.parts[0] == "_inbox":
            continue
        if p.is_dir():
            return False
        if p.suffix == ".mov":
            return False
    return True
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_fs_folders.py -v
```

Expected: all new + old tests PASS.

- [ ] **Step 5: Commit**

```
git add app/fs.py tests/test_fs_folders.py
git commit -m "feat(fs): Folder dataclass + list_folders + folder_exists + folder_is_empty"
```

---

## Task 3: `build_tree` for the recursive template

**Files:**
- Modify: `app/fs.py`
- Test: `tests/test_fs_folders.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_fs_folders.py`:

```python
def test_build_tree_returns_nested_structure(nested_tree):
    root = fs.build_tree()
    # Root is synthetic; its subfolders should include "multiturbo",
    # "check-in", and "Clients" (all at depth 0).
    child_names = [sf.name for sf in root.subfolders]
    assert "Clients" in child_names
    clients = next(sf for sf in root.subfolders if sf.name == "Clients")
    assert [sf.name for sf in clients.subfolders] == ["Acme"]
    # The Acme folder holds the nested meeting.
    acme = clients.subfolders[0]
    assert [m.stem for m in acme.meetings] == ["2026-04-20 09-00-00"]


def test_build_tree_puts_root_meetings_on_root_node(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "rootcast.mov").write_bytes(b"\x00")
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    root = fs.build_tree()
    assert [m.stem for m in root.meetings] == ["rootcast"]
    assert root.subfolders == []
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_fs_folders.py::test_build_tree_returns_nested_structure -v
```

Expected: `AttributeError` on `build_tree`.

- [ ] **Step 3: Implement `build_tree`**

Add to `app/fs.py`:

```python
@dataclass
class TreeNode:
    path: str
    name: str
    subfolders: list["TreeNode"]
    meetings: list[Meeting]


def build_tree(include_inbox: bool = False) -> TreeNode:
    """Builds a nested TreeNode matching the on-disk hierarchy.

    The returned node represents root (path="", name=""). Every folder and
    meeting is placed under its parent path. _inbox is excluded unless
    include_inbox is True (currently unused by callers — inbox is its own tab).
    """
    root = TreeNode(path="", name="", subfolders=[], meetings=[])
    by_path: dict[str, TreeNode] = {"": root}

    for folder in list_folders():
        node = TreeNode(path=folder.path, name=folder.name,
                        subfolders=[], meetings=[])
        by_path[folder.path] = node
        by_path.get(folder.parent, root).subfolders.append(node)

    for m in list_meetings(include_inbox=include_inbox):
        node = by_path.get(m.subdir, root)
        node.meetings.append(m)

    return root
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_fs_folders.py -v
```

Expected: both new tests PASS.

- [ ] **Step 5: Commit**

```
git add app/fs.py tests/test_fs_folders.py
git commit -m "feat(fs): build_tree returns nested folder + meeting structure"
```

---

## Task 4: `move_meeting_artifacts` with rollback

**Files:**
- Modify: `app/fs.py`
- Test: `tests/test_fs_folders.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_fs_folders.py`:

```python
def test_move_meeting_artifacts_moves_all_four_files(nested_tree):
    stem = "2026-04-20 09-00-00"
    fs.move_meeting_artifacts(stem, "Clients/Acme", "Moved")
    assert (nested_tree / "data" / "Moved" / f"{stem}.mov").exists()
    assert (nested_tree / "transcripts" / "Moved" / f"{stem}.txt").exists()
    assert (nested_tree / "information" / "Moved" / f"{stem}-knowledge.md").exists()
    assert (nested_tree / "information" / "Moved" / f"{stem}-commitments.md").exists()
    # Sources gone
    assert not (nested_tree / "data" / "Clients" / "Acme" / f"{stem}.mov").exists()


def test_move_meeting_artifacts_skips_missing_optional_files(tmp_path, monkeypatch):
    data = tmp_path / "data" / "A"
    data.mkdir(parents=True)
    (data / "alone.mov").write_bytes(b"\x00")
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    fs.move_meeting_artifacts("alone", "A", "B")
    assert (tmp_path / "data" / "B" / "alone.mov").exists()
    # Optional files never existed; no crash.


def test_move_meeting_artifacts_raises_when_mov_missing(tmp_path, monkeypatch):
    (tmp_path / "data" / "A").mkdir(parents=True)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    with pytest.raises(FileNotFoundError):
        fs.move_meeting_artifacts("nope", "A", "B")


def test_move_meeting_artifacts_rolls_back_on_collision(nested_tree):
    stem = "2026-04-20 09-00-00"
    # Pre-create a collision for the transcript — the data-level move will
    # succeed but the transcript move will fail, forcing rollback.
    (nested_tree / "transcripts" / "Blocked").mkdir(parents=True, exist_ok=True)
    (nested_tree / "transcripts" / "Blocked" / f"{stem}.txt").write_text("x")
    with pytest.raises(FileExistsError):
        fs.move_meeting_artifacts(stem, "Clients/Acme", "Blocked")
    # .mov should have been rolled back to its original location.
    assert (nested_tree / "data" / "Clients" / "Acme" / f"{stem}.mov").exists()
    assert not (nested_tree / "data" / "Blocked" / f"{stem}.mov").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_fs_folders.py -v -k move_meeting_artifacts
```

Expected: 4 AttributeError / failures.

- [ ] **Step 3: Implement `move_meeting_artifacts`**

Add to `app/fs.py` (requires `import shutil` at top if not present):

```python
_MEETING_SUFFIXES = [
    (DATA_DIR,        ".mov",            False),  # required
    (TRANSCRIPTS_DIR, ".txt",            True),
    (INFORMATION_DIR, "-knowledge.md",   True),
    (INFORMATION_DIR, "-commitments.md", True),
]


def move_meeting_artifacts(stem: str, src_subdir: str, dst_subdir: str) -> list[Path]:
    """Move a meeting's four known files from <root>/<src>/<stem>{suffix} to
    <root>/<dst>/<stem>{suffix}. The .mov is required; the other three are
    optional (a meeting mid-pipeline may not have them yet). If any move
    after the first raises, earlier moves are rolled back."""
    plan: list[tuple[Path, Path, bool]] = []
    for root, suffix, optional in _MEETING_SUFFIXES:
        src = root / src_subdir / f"{stem}{suffix}"
        dst = root / dst_subdir / f"{stem}{suffix}"
        plan.append((src, dst, optional))

    # Preflight: required source must exist; all destinations must be free.
    first_src, first_dst, _ = plan[0]
    if not first_src.exists():
        raise FileNotFoundError(f"{first_src} missing (required)")
    for _, dst, _ in plan:
        if dst.exists():
            raise FileExistsError(f"{dst} already exists")

    moved: list[tuple[Path, Path]] = []
    try:
        for src, dst, optional in plan:
            if not src.exists() and optional:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append((src, dst))
        return [dst for _, dst in moved]
    except Exception:
        for src, dst in reversed(moved):
            try:
                shutil.move(str(dst), str(src))
            except Exception:
                pass
        raise
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_fs_folders.py -v -k move_meeting_artifacts
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```
git add app/fs.py tests/test_fs_folders.py
git commit -m "feat(fs): move_meeting_artifacts atomic 4-file move with rollback"
```

---

## Task 5: `move_folder_tree` with rollback

**Files:**
- Modify: `app/fs.py`
- Test: `tests/test_fs_folders.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_fs_folders.py`:

```python
def test_move_folder_tree_moves_three_parallel_trees(nested_tree):
    stems = fs.move_folder_tree("Clients/Acme", "Renamed")
    assert stems == ["2026-04-20 09-00-00"]
    assert (nested_tree / "data" / "Renamed" / "2026-04-20 09-00-00.mov").exists()
    assert (nested_tree / "transcripts" / "Renamed" / "2026-04-20 09-00-00.txt").exists()
    assert (nested_tree / "information" / "Renamed" / "2026-04-20 09-00-00-knowledge.md").exists()
    # Sources gone
    assert not (nested_tree / "data" / "Clients" / "Acme").exists()


def test_move_folder_tree_raises_on_destination_collision(nested_tree):
    (nested_tree / "data" / "Blocked").mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileExistsError):
        fs.move_folder_tree("Clients/Acme", "Blocked")
    # Source still present.
    assert (nested_tree / "data" / "Clients" / "Acme").exists()


def test_move_folder_tree_rolls_back_partial_move(nested_tree):
    # Pre-create a transcripts collision — the data-level move will succeed
    # but the transcripts-level move will fail. Ensure data/ is restored.
    (nested_tree / "transcripts" / "Collide").mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileExistsError):
        fs.move_folder_tree("Clients/Acme", "Collide")
    assert (nested_tree / "data" / "Clients" / "Acme").exists()
    assert not (nested_tree / "data" / "Collide").exists()


def test_move_folder_tree_refuses_empty_source(nested_tree):
    with pytest.raises(ValueError):
        fs.move_folder_tree("", "Somewhere")
```

- [ ] **Step 2: Run tests**

```
pytest tests/test_fs_folders.py -v -k move_folder_tree
```

Expected: 4 AttributeError / failures.

- [ ] **Step 3: Implement `move_folder_tree`**

Add to `app/fs.py`:

```python
def move_folder_tree(src_path: str, dst_path: str) -> list[str]:
    """Move an entire folder (with all descendants) across the three parallel
    trees. Returns the list of meeting stems now under the new location so
    callers can reindex. Raises FileExistsError on collisions; ValueError for
    empty src; FileNotFoundError if the source doesn't exist on disk."""
    if not src_path:
        raise ValueError("Cannot move root")

    roots = [DATA_DIR, TRANSCRIPTS_DIR, INFORMATION_DIR]
    sources = [r / src_path for r in roots]
    destinations = [r / dst_path for r in roots]

    if not sources[0].is_dir():
        raise FileNotFoundError(f"{sources[0]} is not a directory")
    for dst in destinations:
        if dst.exists():
            raise FileExistsError(f"{dst} already exists")

    moved: list[tuple[Path, Path]] = []
    try:
        for src, dst in zip(sources, destinations):
            if not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append((src, dst))
        new_root = DATA_DIR / dst_path
        return sorted(p.stem for p in new_root.rglob("*.mov"))
    except Exception:
        for src, dst in reversed(moved):
            try:
                shutil.move(str(dst), str(src))
            except Exception:
                pass
        raise
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_fs_folders.py -v -k move_folder_tree
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```
git add app/fs.py tests/test_fs_folders.py
git commit -m "feat(fs): move_folder_tree atomic three-tree move with rollback"
```

---

## Task 6: `app/folders.py` validation module

**Files:**
- Create: `app/folders.py`
- Create: `tests/test_folders_validation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_folders_validation.py`:

```python
import pytest

from app.folders import (
    MAX_NAME_LEN,
    validate_folder_name,
    validate_folder_path,
)


class TestValidateFolderName:
    def test_trims_whitespace(self):
        assert validate_folder_name("  Clients  ") == "Clients"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_folder_name("   ")

    def test_rejects_reserved_names(self):
        for name in [".", "..", "_inbox"]:
            with pytest.raises(ValueError, match="reserved"):
                validate_folder_name(name)

    def test_rejects_slash(self):
        with pytest.raises(ValueError, match="'/' or '"):
            validate_folder_name("a/b")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError, match="'/' or '"):
            validate_folder_name("a\\b")

    def test_rejects_overlong_name(self):
        with pytest.raises(ValueError, match="too long"):
            validate_folder_name("x" * (MAX_NAME_LEN + 1))

    def test_accepts_unicode(self):
        assert validate_folder_name("Español") == "Español"


class TestValidateFolderPath:
    def test_root_is_valid(self):
        assert validate_folder_path("") == ""
        assert validate_folder_path("   ") == ""

    def test_accepts_nested(self):
        assert validate_folder_path("Clients/Acme/Q1") == "Clients/Acme/Q1"

    def test_strips_surrounding_whitespace(self):
        assert validate_folder_path("  Clients/Acme  ") == "Clients/Acme"

    def test_rejects_leading_slash(self):
        with pytest.raises(ValueError, match="start or end"):
            validate_folder_path("/Clients")

    def test_rejects_trailing_slash(self):
        with pytest.raises(ValueError, match="start or end"):
            validate_folder_path("Clients/")

    def test_each_segment_runs_through_name_check(self):
        with pytest.raises(ValueError, match="reserved"):
            validate_folder_path("Clients/../secrets")
```

- [ ] **Step 2: Run tests**

```
pytest tests/test_folders_validation.py -v
```

Expected: all fail — `ModuleNotFoundError`.

- [ ] **Step 3: Create `app/folders.py`**

```python
"""Pure validation helpers for folder names and paths.

No I/O. Every ValueError message is user-facing (displayed in the tree
banner), so keep it short and concrete.
"""
from __future__ import annotations

_INVALID_NAME_CHARS = frozenset("/\\")
_RESERVED_NAMES = frozenset({".", "..", "_inbox"})
MAX_NAME_LEN = 80


def validate_folder_name(name: str) -> str:
    """Normalize + validate a single folder name segment.

    Returns the cleaned name. Raises ValueError with a user-facing message.
    """
    n = (name or "").strip()
    if not n:
        raise ValueError("Name can't be empty.")
    if n in _RESERVED_NAMES:
        raise ValueError(f"'{n}' is a reserved name.")
    if any(c in _INVALID_NAME_CHARS for c in n):
        raise ValueError("Name can't contain '/' or '\\'.")
    if len(n) > MAX_NAME_LEN:
        raise ValueError(f"Name too long (max {MAX_NAME_LEN} characters).")
    return n


def validate_folder_path(path: str) -> str:
    """Validate a full folder path.

    Empty/whitespace → "" (root, valid as a destination). Otherwise every
    segment runs through validate_folder_name.
    """
    p = (path or "").strip()
    if not p:
        return ""
    if p.startswith("/") or p.endswith("/"):
        raise ValueError("Path can't start or end with '/'.")
    segments = [validate_folder_name(seg) for seg in p.split("/")]
    return "/".join(segments)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_folders_validation.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add app/folders.py tests/test_folders_validation.py
git commit -m "feat(folders): validate_folder_name + validate_folder_path"
```

---

## Task 7: Refactor meetings/media/search routes to stem-only URLs

This is the largest mechanical refactor. Do it in one commit so the app stays deployable.

**Files:**
- Modify: `app/routes/meetings.py` (drop `{subdir}` from every handler)
- Modify: `app/routes/media.py`
- Modify: `app/routes/search_routes.py`
- Modify: `templates/_meeting_detail.html` (action URLs; add breadcrumb)
- Modify: `templates/_meeting_row.html` (meeting link)
- Modify: `templates/_meeting_tree.html` (meeting link only — recursive rewrite happens in Task 11)
- Modify: `templates/_search_hit.html` (if present) — any template linking `/meetings/<subdir>/<stem>`
- Modify: `tests/test_routes_meetings.py` — rewrite all URLs
- Modify: `tests/test_video.py` — rewrite all URLs
- Modify: `tests/test_routes_search.py` — rewrite any asserted deep-link shape

- [ ] **Step 1: Pin every URL to update**

```
grep -nE "/meetings/\{subdir\}|/meetings/[^/]+/[^/]+|/video/meeting/" app templates tests | tee /tmp/stem_url_audit.txt | wc -l
```

Read `/tmp/stem_url_audit.txt` end-to-end. Every hit must be converted. Don't let the commit pass until the grep returns only the new stem-only form (or unrelated matches like CSS class names).

- [ ] **Step 2: Update `app/routes/meetings.py`**

Find every route decorated with `/meetings/{subdir}/{stem}...` and rewrite to `/meetings/{stem}...`. Remove `subdir: str` from the signatures; replace `fs.find_meeting(subdir, stem)` with `fs.find_meeting_by_stem(stem)` (returns `None`, not an error).

Example transformation (apply to all handlers):

```python
# Before
@router.get("/meetings/{subdir}/{stem}")
def meeting_detail(request: Request, subdir: str, stem: str):
    m = fs.find_meeting(subdir, stem)
    if m is None:
        raise HTTPException(status_code=404)
    ...

# After
@router.get("/meetings/{stem}")
def meeting_detail(request: Request, stem: str):
    m = fs.find_meeting_by_stem(stem)
    if m is None:
        raise HTTPException(status_code=404)
    ...
```

Apply the same pattern to `tags`, `reextract`, `reclassify`, `suggest-tags`.

- [ ] **Step 3: Update `app/routes/media.py`**

```python
# Before
@router.get("/video/meeting/{subdir}/{stem}")
def video_meeting(subdir: str, stem: str):
    m = fs.find_meeting(subdir, stem)
    ...

# After
@router.get("/video/meeting/{stem}")
def video_meeting(stem: str):
    m = fs.find_meeting_by_stem(stem)
    ...
```

`_inbox` meetings should still resolve — `find_meeting_by_stem` uses `include_inbox=True`.

- [ ] **Step 4: Update `app/routes/search_routes.py`**

The deep-link builder in search results currently formats `/meetings/{subdir|urlencode}/{stem|urlencode}?subtab=...`. Change the builder (both Python-side in the JSON endpoint and any template) to `/meetings/{stem|urlencode}?subtab=...`.

- [ ] **Step 5: Update templates**

For each template that emits a meeting URL, drop the `subdir` segment:

```jinja
# Before
<a href="/meetings/{{ meeting.subdir|urlencode }}/{{ meeting.stem|urlencode }}">
# After
<a href="/meetings/{{ meeting.stem|urlencode }}">
```

In `templates/_meeting_detail.html`, replace the subdir-in-URL pattern for action forms:

```jinja
# Before
<form action="/meetings/{{ meeting.subdir|urlencode }}/{{ meeting.stem|urlencode }}/tags" method="post">
# After
<form action="/meetings/{{ meeting.stem|urlencode }}/tags" method="post">
```

Add a breadcrumb near the top of `_meeting_detail.html`, just above the H2 title:

```jinja
{% if meeting.subdir %}
  <div class="crumbs">
    {% set parts = meeting.subdir.split("/") %}
    {% for p in parts %}<span>{{ p }}</span>{% if not loop.last %} / {% endif %}{% endfor %}
  </div>
{% endif %}
```

- [ ] **Step 6: Update tests — tests/test_routes_meetings.py**

Replace every `/meetings/{subdir}/{stem}` with `/meetings/{stem}`:

```python
# Before
r = client.get(f"/meetings/{subdir}/{stem}")
# After
r = client.get(f"/meetings/{stem}")
```

Same pattern for every `client.post(...)`.

Then swap the `client` fixture to seed a nested tree. At the top of `tests/test_routes_meetings.py`, replace:

```python
from tests.helpers.sample_assets import build_sample_tree
```

with:

```python
from tests.helpers.sample_assets import build_nested_sample_tree as build_sample_tree
```

(The alias keeps every `build_sample_tree(tmp_path)` call site unchanged; the nested builder is a superset, so existing assertions still hold.)

Add two new tests at the bottom of the file:

```python
def test_meeting_detail_resolves_by_stem_from_nested_subdir(client):
    r = client.get("/meetings/2026-04-20 09-00-00")
    assert r.status_code == 200
    # Breadcrumb shown in the detail view for nested meeting.
    assert "Clients" in r.text
    assert "Acme" in r.text


def test_meeting_tags_post_resolves_by_stem(client):
    r = client.post(
        "/meetings/2026-04-14 17-00-43/tags",
        data={"tag_name": ["topic-x"], "tag_type": ["topic"]},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)
```

- [ ] **Step 7: Update tests — tests/test_video.py**

```python
# Before
r = client.get(f"/video/meeting/{subdir}/{stem}")
# After
r = client.get(f"/video/meeting/{stem}")
```

- [ ] **Step 8: Update tests — tests/test_routes_search.py**

If any test asserts on the exact shape of a deep link (`"/meetings/multiturbo/…"`), change the assertion to match the new stem-only shape.

- [ ] **Step 9: Run the full suite**

```
pytest -q
```

Expected: all 199+ tests green. If anything fails, re-grep `/tmp/stem_url_audit.txt` for a template or test you missed.

- [ ] **Step 10: Commit**

```
git add app/routes/meetings.py app/routes/media.py app/routes/search_routes.py \
        templates/_meeting_detail.html templates/_meeting_row.html \
        templates/_meeting_tree.html \
        tests/test_routes_meetings.py tests/test_video.py tests/test_routes_search.py
git commit -m "refactor: stem-only meeting URLs in preparation for nested subdirs"
```

---

## Task 8: Refactor `inbox_apply` to use `fs.move_meeting_artifacts` + `folders.validate_folder_path`

**Files:**
- Modify: `app/routes/inbox.py`
- Modify: `tests/test_routes_inbox.py`

- [ ] **Step 1: Write a new spy test**

In `tests/test_routes_inbox.py`, add:

```python
def test_inbox_apply_routes_through_move_meeting_artifacts(client, monkeypatch):
    from app import fs as _fs
    calls = []

    def spy(stem, src, dst):
        calls.append((stem, src, dst))
        # Delegate to the real impl so downstream reindex still works.
        return _fs.move_meeting_artifacts(stem, src, dst)

    monkeypatch.setattr("app.routes.inbox.fs.move_meeting_artifacts", spy)
    _seed_proposal("m-via-helper", "multiturbo", [])
    r = client.post(
        "/inbox/m-via-helper/apply",
        data={"target_subdir": "multiturbo", "tag_name": [], "tag_type": []},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert calls == [("m-via-helper", "_inbox", "multiturbo")]


def test_inbox_apply_accepts_nested_target_subdir(client):
    _seed_proposal("m-nested-apply", "", [])
    r = client.post(
        "/inbox/m-nested-apply/apply",
        data={"target_subdir": "Clients/Acme", "tag_name": [], "tag_type": []},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Moved into the nested location.
    from app import fs as _fs
    assert (_fs.DATA_DIR / "Clients" / "Acme" / "m-nested-apply.mov").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_routes_inbox.py -v -k "helper or nested_target"
```

Expected: both fail. The second fails because current code rejects `/` in target_subdir.

- [ ] **Step 3: Refactor `inbox_apply`**

In `app/routes/inbox.py`:

```python
# Replace the imports block top-of-file to add:
from app import folders as folders_module  # alias to avoid clashing with `folders` route
```

Find the validation block (currently around lines 132-136):

```python
# Before
target_subdir = target_subdir.strip()
if not target_subdir:
    raise HTTPException(status_code=400, detail="target_subdir is required")
if "/" in target_subdir or "\\" in target_subdir or ".." in target_subdir:
    raise HTTPException(status_code=400, detail="invalid target_subdir")
```

Replace with:

```python
try:
    target_subdir = folders_module.validate_folder_path(target_subdir)
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
if not target_subdir:
    raise HTTPException(status_code=400, detail="target_subdir is required")
```

Find the move block (currently lines 138-151) and replace the 4-tuple list + loop with:

```python
fs.move_meeting_artifacts(stem, store.INBOX_SUBDIR, target_subdir)
```

Broaden the datalist source. Find `_existing_subdirs()` (around line 32) and change it to:

```python
def _existing_subdirs() -> list[str]:
    return [f.path for f in fs.list_folders()]
```

- [ ] **Step 4: Run full inbox test file**

```
pytest tests/test_routes_inbox.py -v
```

Expected: all tests pass — the new two plus the existing ~25.

- [ ] **Step 5: Run full suite**

```
pytest -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```
git add app/routes/inbox.py tests/test_routes_inbox.py
git commit -m "refactor(inbox): route apply through fs.move_meeting_artifacts + folders.validate_folder_path"
```

---

## Task 9: `app/routes/folders.py` with CRUD + move routes

**Files:**
- Create: `app/routes/folders.py`
- Modify: `server.py` (register the router)
- Create: `tests/test_routes_folders.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_routes_folders.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app import fs, store
from server import create_app
from tests.helpers.sample_assets import build_nested_sample_tree


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_nested_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    return TestClient(create_app())


def test_create_root_level_folder(client, tmp_path):
    r = client.post("/folders/create", data={"parent_path": "", "name": "Clients2"})
    assert r.status_code == 200
    assert (tmp_path / "data" / "Clients2").is_dir()
    assert (tmp_path / "transcripts" / "Clients2").is_dir()
    assert (tmp_path / "information" / "Clients2").is_dir()


def test_create_nested_folder(client, tmp_path):
    r = client.post("/folders/create", data={"parent_path": "Clients", "name": "Beta"})
    assert r.status_code == 200
    assert (tmp_path / "data" / "Clients" / "Beta").is_dir()


def test_create_refuses_collision(client):
    r = client.post("/folders/create", data={"parent_path": "", "name": "Clients"})
    assert r.status_code == 200
    assert "already exists" in r.text.lower()


def test_create_refuses_invalid_name(client):
    for bad in ["..", "_inbox", "a/b", ""]:
        r = client.post("/folders/create", data={"parent_path": "", "name": bad})
        assert r.status_code == 200
        assert "tree-banner" in r.text


def test_rename_moves_all_three_trees_and_reindexes(client, tmp_path, monkeypatch):
    reindexed = []
    from app import search as _s
    monkeypatch.setattr(_s, "reindex_meeting", lambda stem: reindexed.append(stem))
    r = client.post("/folders/rename", data={"path": "Clients/Acme", "new_name": "Beta"})
    assert r.status_code == 200
    assert (tmp_path / "data" / "Clients" / "Beta" / "2026-04-20 09-00-00.mov").exists()
    assert (tmp_path / "transcripts" / "Clients" / "Beta" / "2026-04-20 09-00-00.txt").exists()
    assert "2026-04-20 09-00-00" in reindexed


def test_rename_refuses_root(client):
    r = client.post("/folders/rename", data={"path": "", "new_name": "foo"})
    assert r.status_code == 200
    assert "tree-banner" in r.text


def test_rename_refuses_inbox(client):
    r = client.post("/folders/rename", data={"path": "_inbox", "new_name": "foo"})
    assert r.status_code == 200
    assert "tree-banner" in r.text


def test_delete_empty_folder_removes_from_all_three_trees(client, tmp_path):
    (tmp_path / "data" / "Empty").mkdir()
    (tmp_path / "transcripts" / "Empty").mkdir(parents=True, exist_ok=True)
    (tmp_path / "information" / "Empty").mkdir(parents=True, exist_ok=True)
    r = client.post("/folders/delete", data={"path": "Empty"})
    assert r.status_code == 200
    assert not (tmp_path / "data" / "Empty").exists()


def test_delete_non_empty_folder_refused_with_banner(client):
    r = client.post("/folders/delete", data={"path": "Clients"})
    assert r.status_code == 200
    assert "move contents out" in r.text.lower()


def test_delete_refuses_inbox(client):
    r = client.post("/folders/delete", data={"path": "_inbox"})
    assert r.status_code == 200
    assert "tree-banner" in r.text


def test_move_folder_moves_tree_and_reindexes(client, tmp_path, monkeypatch):
    reindexed = []
    from app import search as _s
    monkeypatch.setattr(_s, "reindex_meeting", lambda stem: reindexed.append(stem))
    r = client.post("/folders/move",
                    data={"path": "Clients/Acme", "new_parent_path": ""})
    assert r.status_code == 200
    assert (tmp_path / "data" / "Acme" / "2026-04-20 09-00-00.mov").exists()
    assert "2026-04-20 09-00-00" in reindexed


def test_move_folder_refuses_cycle(client):
    r = client.post("/folders/move",
                    data={"path": "Clients", "new_parent_path": "Clients/Acme"})
    assert r.status_code == 200
    assert "cycle" in r.text.lower() or "into its own" in r.text.lower()


def test_move_folder_refuses_destination_collision(client, tmp_path):
    (tmp_path / "data" / "multiturbo" / "Acme").mkdir(parents=True, exist_ok=True)
    r = client.post("/folders/move",
                    data={"path": "Clients/Acme", "new_parent_path": "multiturbo"})
    assert r.status_code == 200
    assert "already exists" in r.text.lower()
```

- [ ] **Step 2: Run tests**

```
pytest tests/test_routes_folders.py -v
```

Expected: all fail — no `/folders/*` routes exist yet.

- [ ] **Step 3: Create `app/routes/folders.py`**

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import folders as folders_module, fs, search, store
from app.routes._context import nav_counts

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _render_tree_partial(request: Request, *, error: str | None = None) -> HTMLResponse:
    """Render the <aside class='tree'> outerHTML. Optional red banner at the top."""
    tree = fs.build_tree()
    html = templates.get_template("_meeting_tree_partial.html").render(
        request=request,
        tree=tree,
        tree_error=error,
        **nav_counts(),
    )
    return HTMLResponse(html)


def _error(request: Request, msg: str) -> HTMLResponse:
    return _render_tree_partial(request, error=msg)


def _parent_of(path: str) -> str:
    return "/".join(path.split("/")[:-1]) if "/" in path else ""


@router.post("/folders/create", response_class=HTMLResponse)
def create(request: Request,
           parent_path: str = Form(""),
           name: str = Form(...)):
    try:
        parent = folders_module.validate_folder_path(parent_path)
        leaf = folders_module.validate_folder_name(name)
    except ValueError as e:
        return _error(request, str(e))
    target = f"{parent}/{leaf}" if parent else leaf
    if fs.folder_exists(target):
        return _error(request, f"'{target}' already exists.")
    for root in (fs.DATA_DIR, fs.TRANSCRIPTS_DIR, fs.INFORMATION_DIR):
        (root / target).mkdir(parents=True, exist_ok=True)
    return _render_tree_partial(request)


@router.post("/folders/rename", response_class=HTMLResponse)
def rename(request: Request,
           path: str = Form(...),
           new_name: str = Form(...)):
    try:
        src = folders_module.validate_folder_path(path)
        leaf = folders_module.validate_folder_name(new_name)
    except ValueError as e:
        return _error(request, str(e))
    if not src:
        return _error(request, "Cannot rename the root folder.")
    if src == "_inbox" or src.startswith("_inbox/"):
        return _error(request, "'_inbox' is managed by the app.")
    parent = _parent_of(src)
    target = f"{parent}/{leaf}" if parent else leaf
    if target == src:
        return _render_tree_partial(request)
    if fs.folder_exists(target):
        return _error(request, f"'{target}' already exists.")
    try:
        stems = fs.move_folder_tree(src, target)
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        return _error(request, str(e))
    for stem in stems:
        try:
            search.reindex_meeting(stem)
        except Exception:
            pass
    return _render_tree_partial(request)


@router.post("/folders/delete", response_class=HTMLResponse)
def delete(request: Request, path: str = Form(...)):
    try:
        src = folders_module.validate_folder_path(path)
    except ValueError as e:
        return _error(request, str(e))
    if not src:
        return _error(request, "Cannot delete the root folder.")
    if src == "_inbox" or src.startswith("_inbox/"):
        return _error(request, "'_inbox' is managed by the app.")
    if not fs.folder_exists(src):
        return _error(request, f"'{src}' does not exist.")
    if not fs.folder_is_empty(src):
        return _error(request, f"'{src}' is not empty — move contents out first.")
    for root in (fs.DATA_DIR, fs.TRANSCRIPTS_DIR, fs.INFORMATION_DIR):
        p = root / src
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                # Something showed up between the empty-check and now — surface it.
                return _error(request, f"'{src}' became non-empty during delete.")
    return _render_tree_partial(request)


@router.post("/folders/move", response_class=HTMLResponse)
def move(request: Request,
         path: str = Form(...),
         new_parent_path: str = Form("")):
    try:
        src = folders_module.validate_folder_path(path)
        new_parent = folders_module.validate_folder_path(new_parent_path)
    except ValueError as e:
        return _error(request, str(e))
    if not src:
        return _error(request, "Cannot move the root folder.")
    if src == "_inbox" or src.startswith("_inbox/"):
        return _error(request, "'_inbox' is managed by the app.")
    if new_parent == src or new_parent.startswith(src + "/"):
        return _error(request, f"Can't move '{src}' into its own descendant (cycle).")
    basename = src.split("/")[-1]
    target = f"{new_parent}/{basename}" if new_parent else basename
    if target == src:
        return _render_tree_partial(request)
    if fs.folder_exists(target):
        return _error(request, f"'{target}' already exists.")
    # Collision check: every descendant stem must be unique at the destination.
    desc_stems = {m.stem for m in fs.list_meetings(include_inbox=False)
                  if m.subdir == src or m.subdir.startswith(src + "/")}
    for m in fs.list_meetings(include_inbox=True):
        if m.stem in desc_stems and not (m.subdir == src or m.subdir.startswith(src + "/")):
            return _error(request, f"Stem '{m.stem}' already exists elsewhere — aborting move.")
    try:
        stems = fs.move_folder_tree(src, target)
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        return _error(request, str(e))
    for stem in stems:
        try:
            search.reindex_meeting(stem)
        except Exception:
            pass
    return _render_tree_partial(request)
```

- [ ] **Step 4: Register the router in `server.py`**

In `server.py`, find the section that includes the routers and add:

```python
from app.routes import folders as folders_router
...
app.include_router(folders_router.router)
```

- [ ] **Step 5: Create the partial template used by `_render_tree_partial`**

Create `templates/_meeting_tree_partial.html` as a thin wrapper the real tree template can render (Task 11 replaces the inner tree with the recursive macro):

```jinja
<aside class="tree" hx-target=".tree" hx-swap="outerHTML">
  {% if tree_error %}
  <div class="tree-banner" role="alert" data-dismiss-ms="6000">
    <span>{{ tree_error }}</span>
    <button type="button" class="toast-close" aria-label="Dismiss">×</button>
  </div>
  {% endif %}
  {# Placeholder — Task 11 replaces this with the recursive render_node macro. #}
  <div class="tree-placeholder">Tree rendering — see Task 11.</div>
</aside>
```

(Task 11 replaces this body with the recursive macro + hover icons; for Task 9 the banner alone is the visible contract. Tests above only assert `tree-banner` and message substrings, so the placeholder is fine until Task 11.)

- [ ] **Step 6: Run tests**

```
pytest tests/test_routes_folders.py -v
```

Expected: all 12 PASS.

- [ ] **Step 7: Run full suite**

```
pytest -q
```

Expected: green.

- [ ] **Step 8: Commit**

```
git add app/routes/folders.py server.py templates/_meeting_tree_partial.html tests/test_routes_folders.py
git commit -m "feat(folders): CRUD + move routes with tree-partial HTMX response"
```

---

## Task 10: `POST /meetings/{stem}/move` + `GET /meetings/tree-partial`

**Files:**
- Modify: `app/routes/meetings.py`
- Test: `tests/test_routes_folders.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_routes_folders.py`:

```python
def test_meeting_move_changes_subdir_and_reindexes(client, tmp_path, monkeypatch):
    reindexed = []
    from app import search as _s
    monkeypatch.setattr(_s, "reindex_meeting", lambda stem: reindexed.append(stem))
    r = client.post("/meetings/2026-04-20 09-00-00/move",
                    data={"new_subdir": "multiturbo"})
    assert r.status_code == 200
    assert (tmp_path / "data" / "multiturbo" / "2026-04-20 09-00-00.mov").exists()
    assert "2026-04-20 09-00-00" in reindexed


def test_meeting_move_refuses_inbox_destination(client):
    r = client.post("/meetings/2026-04-20 09-00-00/move",
                    data={"new_subdir": "_inbox"})
    assert r.status_code == 200
    assert "_inbox" in r.text


def test_tree_partial_endpoint_returns_aside(client):
    r = client.get("/meetings/tree-partial")
    assert r.status_code == 200
    assert "<aside" in r.text and 'class="tree"' in r.text
```

- [ ] **Step 2: Run tests**

```
pytest tests/test_routes_folders.py -v -k "meeting_move or tree_partial"
```

Expected: all fail.

- [ ] **Step 3: Add the handlers**

In `app/routes/meetings.py`, add near the bottom of the file (after existing handlers):

```python
from fastapi.responses import HTMLResponse

from app import folders as folders_module


@router.get("/meetings/tree-partial", response_class=HTMLResponse)
def tree_partial(request: Request):
    from app.routes.folders import _render_tree_partial
    return _render_tree_partial(request)


@router.post("/meetings/{stem}/move", response_class=HTMLResponse)
def meeting_move(request: Request, stem: str, new_subdir: str = Form("")):
    from app.routes.folders import _render_tree_partial, _error
    try:
        target = folders_module.validate_folder_path(new_subdir)
    except ValueError as e:
        return _error(request, str(e))
    if target == "_inbox" or target.startswith("_inbox/"):
        return _error(request, "'_inbox' is managed by the app.")
    m = fs.find_meeting_by_stem(stem)
    if m is None:
        return _error(request, f"Meeting '{stem}' not found.")
    if m.subdir == target:
        return _render_tree_partial(request)
    # Collision: another meeting with the same stem already at the destination.
    dst_mov = fs.DATA_DIR / target / f"{stem}.mov"
    if dst_mov.exists():
        return _error(request, f"A meeting named '{stem}' already exists at '{target}'.")
    try:
        fs.move_meeting_artifacts(stem, m.subdir, target)
    except (FileExistsError, FileNotFoundError) as e:
        return _error(request, str(e))
    try:
        search.reindex_meeting(stem)
    except Exception:
        pass
    return _render_tree_partial(request)
```

Ensure `Form`, `search`, `fs` are already imported in `meetings.py`; if not, add them at the top.

- [ ] **Step 4: Run tests**

```
pytest tests/test_routes_folders.py -v
```

Expected: all 15 PASS (12 from Task 9 + 3 new).

- [ ] **Step 5: Commit**

```
git add app/routes/meetings.py tests/test_routes_folders.py
git commit -m "feat(meetings): POST /meetings/{stem}/move + GET /meetings/tree-partial"
```

---

## Task 11: Rewrite `_meeting_tree.html` recursively + hover icons + error banner + CSS

**Files:**
- Modify: `templates/_meeting_tree.html`
- Modify: `templates/_meeting_tree_partial.html`
- Modify: `app/routes/meetings.py` (the index handler must pass `tree` instead of `meeting_blocks`)
- Modify: `static/app.css`

- [ ] **Step 1: Rewrite `_meeting_tree.html`**

Replace the entire file contents with:

```jinja
{% macro render_node(node) %}
  {% if node.path %}
  <details class="folder-group" data-folder-path="{{ node.path }}" open>
    <summary class="folder"
             data-move-kind="folder"
             data-move-id="{{ node.path }}"
             draggable="true">
      <span class="folder-name">{{ node.name }}</span>
      <span class="folder-actions">
        <button type="button" class="fi fi-new" title="New subfolder"
                onclick="window.transcribeTree.promptCreate('{{ node.path }}')">➕</button>
        <button type="button" class="fi fi-rename" title="Rename"
                onclick="window.transcribeTree.promptRename('{{ node.path }}', '{{ node.name }}')">✏️</button>
        <button type="button" class="fi fi-del" title="Delete"
                hx-post="/folders/delete"
                hx-target=".tree" hx-swap="outerHTML"
                hx-confirm="Delete folder '{{ node.path }}'?"
                hx-vals='{"path": "{{ node.path }}"}'>🗑</button>
      </span>
    </summary>
  {% endif %}
    <ul class="tree-children">
      {% for sub in node.subfolders %}
        <li>{{ render_node(sub) }}</li>
      {% endfor %}
      {% for m in node.meetings %}
        <li class="tree-leaf"
            data-move-kind="meeting"
            data-move-id="{{ m.stem }}"
            draggable="true">
          <a href="/meetings/{{ m.stem|urlencode }}"
             class="{% if active_stem == m.stem %}hl{% endif %}"
             >{{ m.stem }}</a>
          {% if m.unknown_count %}<span class="badge">{{ m.unknown_count }}</span>{% endif %}
        </li>
      {% endfor %}
    </ul>
  {% if node.path %}
  </details>
  {% endif %}
{% endmacro %}

<div class="tree-toolbar">
  <form hx-post="/folders/create" hx-target=".tree" hx-swap="outerHTML"
        class="new-folder-form">
    <input type="hidden" name="parent_path" value="">
    <input type="text" name="name" placeholder="+ New folder" class="new-folder-input">
  </form>
</div>

<ul class="tree-children tree-root-drop">
  {% for sub in tree.subfolders %}
    <li>{{ render_node(sub) }}</li>
  {% endfor %}
  {% for m in tree.meetings %}
    <li class="tree-leaf"
        data-move-kind="meeting"
        data-move-id="{{ m.stem }}"
        draggable="true">
      <a href="/meetings/{{ m.stem|urlencode }}"
         class="{% if active_stem == m.stem %}hl{% endif %}"
         >{{ m.stem }}</a>
      {% if m.unknown_count %}<span class="badge">{{ m.unknown_count }}</span>{% endif %}
    </li>
  {% endfor %}
</ul>
```

- [ ] **Step 2: Rewrite `_meeting_tree_partial.html`** (the HTMX-returnable wrapper)

```jinja
<aside class="tree" hx-target=".tree" hx-swap="outerHTML">
  {% if tree_error %}
  <div class="tree-banner" role="alert" data-dismiss-ms="6000">
    <span>{{ tree_error }}</span>
    <button type="button" class="toast-close" aria-label="Dismiss">×</button>
  </div>
  {% endif %}
  {% include "_meeting_tree.html" %}
</aside>
```

- [ ] **Step 3: Update the meetings index handler to pass `tree` to the template**

In `app/routes/meetings.py`, find where `meeting_blocks = fs.group_meetings(...)` is constructed for the index route. Replace with:

```python
tree = fs.build_tree()
```

Update the render context key from `meeting_blocks` to `tree`. Also pass `active_stem=None` on the index and `active_stem=stem` on the detail view.

If the existing tree render relied on `fs.group_meetings`'s per-subdir grouping, that remains valuable for folders with many meetings. Task 12 or a follow-up can reintroduce month grouping *inside* the recursive macro; for this task, the tree is flat-per-folder (no month `<details>`) — acceptable for the initial nested-folders ship.

- [ ] **Step 4: Add CSS**

Append to `static/app.css`:

```css
/* Nested tree — folder CRUD + DnD */
.tree-toolbar { padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--border); }
.new-folder-input {
  width: 100%; padding: 0.3rem 0.4rem;
  background: transparent; border: 1px dashed var(--border);
  border-radius: 6px; font: inherit; color: var(--muted); font-size: 0.78rem;
}
.new-folder-input:focus { outline: none; border-color: var(--accent); color: var(--text); }

.folder-group > summary.folder {
  display: flex; align-items: center; gap: 0.4rem;
  cursor: pointer; padding: 0.15rem 0.2rem;
}
.folder-group > summary.folder:hover { color: var(--accent); }
.folder-group .folder-name[contenteditable="true"] {
  outline: 1px solid var(--accent); border-radius: 3px; padding: 0 3px;
}
.folder-actions {
  margin-left: auto; display: inline-flex; gap: 0.2rem;
  opacity: 0; transition: opacity 120ms ease;
}
.folder-group > summary:hover .folder-actions,
.folder-group > summary:focus-within .folder-actions { opacity: 1; }
@media (hover: none) { .folder-actions { opacity: 1; } }

.folder-actions button.fi {
  background: transparent; border: none; cursor: pointer;
  padding: 0 0.15rem; font-size: 0.85rem; line-height: 1;
  color: var(--muted);
}
.folder-actions button.fi:hover { color: var(--accent); }
.folder-actions button.fi.fi-del:hover { color: var(--danger, #b02a37); }

.tree-children { list-style: none; padding-left: 0.85rem; margin: 0; }
.tree-root-drop { padding-left: 0; }
.tree-leaf { display: flex; align-items: center; gap: 0.3rem; padding: 0.1rem 0.2rem; }

/* Drop-target highlight (Task 12 wires this via JS) */
.drop-target { background: color-mix(in srgb, var(--accent) 12%, transparent); border-radius: 4px; }

.tree-banner {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.55rem 0.75rem; margin: 0.4rem 0.5rem;
  background: color-mix(in srgb, var(--danger, #b02a37) 10%, var(--panel));
  color: var(--danger, #b02a37);
  border: 1px solid var(--danger, #b02a37);
  border-radius: 6px; font-size: 0.82rem;
}
.tree-banner .toast-close {
  margin-left: auto; background: transparent; border: none;
  color: inherit; cursor: pointer; font-size: 1rem; line-height: 1;
}
```

- [ ] **Step 5: Run full suite**

```
pytest -q
```

Expected: green. The tree-rendering assertions in `test_routes_meetings.py` may need minor updates — adjust any test that asserts `meeting_blocks` is in context to assert `tree` instead.

- [ ] **Step 6: Manual smoke — UI**

```
python server.py
```

Visit `http://127.0.0.1:8000/meetings`. Confirm:
- Tree renders nested meetings with the right indent.
- Hovering a folder shows the three action icons.
- Typing in the "+ New folder" input and pressing Enter creates a new folder (tree refreshes).
- Clicking 🗑 on an empty folder works; clicking it on a non-empty folder shows the red banner.
- The ✏️ icon makes the folder name editable inline (the save-on-blur wiring is minimal here — Task 12 can polish if needed; for now the user-facing rename button will appear alongside the input when I add DnD).

- [ ] **Step 7: Commit**

```
git add templates/_meeting_tree.html templates/_meeting_tree_partial.html \
        app/routes/meetings.py static/app.css
git commit -m "feat(tree): recursive nested render + hover actions + error banner"
```

---

## Task 12: Drag-and-drop JS + draggable attributes + drop-target integration

**Files:**
- Create: `static/tree_dnd.js`
- Modify: `templates/base.html`
- Modify: `templates/_meeting_tree.html` (root drop zone marker)

- [ ] **Step 1: Create `static/tree_dnd.js`**

```javascript
// Drag-and-drop for the /meetings nested tree.
// Every row with [data-move-kind] is draggable. Every folder <summary> and
// the root <ul class="tree-root-drop"> are drop targets. On drop we POST to
// /folders/move or /meetings/{stem}/move, then ask HTMX to repaint .tree.
(function () {
  function onDragStart(e) {
    const src = e.target.closest("[data-move-kind]");
    if (!src) return;
    e.dataTransfer.setData("application/x-transcribe-move", JSON.stringify({
      kind: src.dataset.moveKind,
      id: src.dataset.moveId,
    }));
    e.dataTransfer.effectAllowed = "move";
  }

  function findDropTarget(el) {
    if (!el) return null;
    const folderSummary = el.closest("summary.folder");
    if (folderSummary) return { kind: "folder", path: folderSummary.parentElement.dataset.folderPath };
    const rootUl = el.closest(".tree-root-drop");
    if (rootUl) return { kind: "folder", path: "" };
    return null;
  }

  function onDragOver(e) {
    const tgt = findDropTarget(e.target);
    if (!tgt) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const node = e.target.closest("summary.folder") || e.target.closest(".tree-root-drop");
    if (node) node.classList.add("drop-target");
  }

  function onDragLeave(e) {
    const node = e.target.closest("summary.folder") || e.target.closest(".tree-root-drop");
    if (node) node.classList.remove("drop-target");
  }

  async function onDrop(e) {
    const tgt = findDropTarget(e.target);
    if (!tgt) return;
    e.preventDefault();
    const node = e.target.closest("summary.folder") || e.target.closest(".tree-root-drop");
    if (node) node.classList.remove("drop-target");
    let payload;
    try { payload = JSON.parse(e.dataTransfer.getData("application/x-transcribe-move")); }
    catch { return; }
    // Client-side guard — cycle for folder moves.
    if (payload.kind === "folder" && (tgt.path === payload.id || tgt.path.startsWith(payload.id + "/"))) return;

    const body = new URLSearchParams();
    let url;
    if (payload.kind === "folder") {
      url = "/folders/move";
      body.set("path", payload.id);
      body.set("new_parent_path", tgt.path);
    } else {
      url = `/meetings/${encodeURIComponent(payload.id)}/move`;
      body.set("new_subdir", tgt.path);
    }
    const resp = await fetch(url, { method: "POST", body });
    if (!resp.ok) return;
    const html = await resp.text();
    const el = document.querySelector(".tree");
    if (el) el.outerHTML = html;
  }

  async function postForm(url, fields) {
    const body = new URLSearchParams();
    for (const [k, v] of Object.entries(fields)) body.set(k, v);
    const resp = await fetch(url, { method: "POST", body });
    if (!resp.ok) return;
    const html = await resp.text();
    const el = document.querySelector(".tree");
    if (el) el.outerHTML = html;
  }

  async function promptCreate(parentPath) {
    const name = window.prompt("New folder name:");
    if (name === null || !name.trim()) return;
    await postForm("/folders/create", { parent_path: parentPath, name });
  }

  async function promptRename(path, currentName) {
    const name = window.prompt("New name for '" + currentName + "':", currentName);
    if (name === null || !name.trim() || name === currentName) return;
    await postForm("/folders/rename", { path, new_name: name });
  }

  function install() {
    const tree = document.querySelector(".tree");
    if (!tree) return;
    tree.addEventListener("dragstart", onDragStart);
    tree.addEventListener("dragover", onDragOver);
    tree.addEventListener("dragleave", onDragLeave);
    tree.addEventListener("drop", onDrop);
  }

  window.transcribeTree = { promptCreate, promptRename };

  document.addEventListener("DOMContentLoaded", install);
  // HTMX replaces the whole <aside class="tree"> — re-install after swaps.
  document.addEventListener("htmx:afterSwap", install);
})();
```

- [ ] **Step 2: Include the script in `templates/base.html`**

Find where other `<script>` tags live (likely near the bottom of `<body>`) and add:

```html
<script src="/static/tree_dnd.js" defer></script>
```

- [ ] **Step 3: Confirm the root drop zone marker exists**

In `templates/_meeting_tree.html`, the outer `<ul>` wrapping root-level items should already have `class="tree-children tree-root-drop"` from Task 11. If not, add it.

- [ ] **Step 4: Manual smoke**

Restart the server. In the browser:
1. Drag a meeting row onto a folder → release. Meeting moves; the tree repaints with the meeting now under that folder.
2. Drag a folder onto another folder → release. Nested move; descendants follow.
3. Drag a folder onto *one of its own descendants* → nothing happens (client-side guard).
4. Drag a meeting/folder onto the root area (above all folders) → moves to root.

If any step fails, check the browser console for `fetch` errors and the server log for the actual HTTP status.

- [ ] **Step 5: Commit**

```
git add static/tree_dnd.js templates/base.html templates/_meeting_tree.html
git commit -m "feat(tree): drag-and-drop move wiring for meetings and folders"
```

---

## Task 13: Startup stem-uniqueness warning

**Files:**
- Modify: `app/fs.py`
- Modify: `server.py`
- Create: `tests/test_stem_uniqueness_warning.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_stem_uniqueness_warning.py`:

```python
import logging

import pytest

from app import fs


def test_assert_stem_uniqueness_warns_on_duplicates(tmp_path, monkeypatch, caplog):
    (tmp_path / "data" / "A").mkdir(parents=True)
    (tmp_path / "data" / "B").mkdir(parents=True)
    (tmp_path / "data" / "A" / "dup.mov").write_bytes(b"\x00")
    (tmp_path / "data" / "B" / "dup.mov").write_bytes(b"\x00")
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    with caplog.at_level(logging.WARNING):
        fs.assert_stem_uniqueness_or_warn()
    assert any("duplicate stem 'dup'" in rec.message for rec in caplog.records)


def test_assert_stem_uniqueness_silent_on_unique(tmp_path, monkeypatch, caplog):
    (tmp_path / "data" / "A").mkdir(parents=True)
    (tmp_path / "data" / "A" / "unique.mov").write_bytes(b"\x00")
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    with caplog.at_level(logging.WARNING):
        fs.assert_stem_uniqueness_or_warn()
    assert not any("duplicate stem" in rec.message for rec in caplog.records)
```

- [ ] **Step 2: Run tests**

```
pytest tests/test_stem_uniqueness_warning.py -v
```

Expected: fail — `assert_stem_uniqueness_or_warn` doesn't exist yet.

- [ ] **Step 3: Implement**

Add to `app/fs.py`:

```python
import logging

_log = logging.getLogger(__name__)


def assert_stem_uniqueness_or_warn() -> None:
    """Emit a WARNING log line for every stem that appears more than once
    across data/ (including _inbox). Never raises — duplicates are legal on
    disk, they just break move/rename preflight checks."""
    by_stem: dict[str, list[str]] = {}
    for m in list_meetings(include_inbox=True):
        by_stem.setdefault(m.stem, []).append(m.subdir or "(root)")
    for stem, locations in by_stem.items():
        if len(locations) > 1:
            _log.warning("duplicate stem %r found at %s", stem, locations)
```

- [ ] **Step 4: Call it from `create_app`**

In `server.py`, inside `create_app()` (after `store.init_schema()`):

```python
fs.assert_stem_uniqueness_or_warn()
```

- [ ] **Step 5: Run full suite**

```
pytest -q
```

Expected: all green. ~235 tests.

- [ ] **Step 6: Commit**

```
git add app/fs.py server.py tests/test_stem_uniqueness_warning.py
git commit -m "feat(fs): startup WARNING on duplicate meeting stems"
```

---

## Final verification

- [ ] **Run the full suite**

```
pytest -q
```

Target: 194 → ~235 tests green.

- [ ] **Manual end-to-end smoke** (per the design spec's verification list)

1. Start server; tree renders; existing meeting links resolve at `/meetings/{stem}`.
2. `+ New folder` → `Clients`; disk shows `data/Clients/`, `transcripts/Clients/`, `information/Clients/`.
3. Hover `Clients`, click ➕, name `Acme`; nested `data/Clients/Acme/` created.
4. Drag an existing meeting into `Clients/Acme`; all 4 files moved; detail view shows breadcrumb `Clients / Acme`.
5. Drag `Clients/Acme` into a sibling folder; contents follow; search still finds it.
6. Drag `Clients` into `Clients/Acme` → refused (no network call fires).
7. 🗑 a non-empty folder → red banner "not empty — move contents out first."
8. ✏️ rename `Acme` to `Acme-prod`; all three trees renamed; FTS shows updated subdir.
9. `/inbox` Apply to `Clients/Acme-prod` works; datalist lists the nested path.
10. Seed a duplicate stem, restart, confirm WARNING in log; drag one duplicate somewhere → collision banner.

- [ ] **Push**

```
git push origin <feature-branch>
```

Commit messages stand alone for each task — reviewers can walk the history top-down. No squash required; if the branch is used as-is, the history is the narrative.

## Out of scope (explicit non-goals from the spec)

- Touch-device drag-and-drop (hover icons already degrade to always-visible on `@media (hover: none)`).
- Sibling reordering within a folder (only "drop INTO a folder" is supported).
- Playwright-backed DnD tests (server-side endpoints are fully covered; DnD is a manual smoke).
- Old-URL redirects for `/meetings/{subdir}/{stem}` (local-only app; acceptable break).
- DB-backed folder metadata, custom sort orders, or trash/undo (potential follow-ups).

## Deviations from the spec (documented)

- **Per-folder month grouping is deferred.** The spec calls for `fs.group_meetings`'s `YYYY-MM` month `<details>` buckets to keep working inside each folder when that folder has >10 meetings. This plan ships the recursive tree without month grouping — meetings just list flat inside a folder. Reintroducing month buckets inside the recursive macro is a small follow-up (one template change + use of the existing `fs.group_meetings` helper scoped per node). Keeping it out of this round reduces the template's surface area during the nesting + DnD change and shortens review.
