from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app import folders as folders_module, fs, search
from app.routes._tree import render_tree_partial, error as tree_error

_log = logging.getLogger(__name__)

router = APIRouter()


def _parent_of(path: str) -> str:
    return "/".join(path.split("/")[:-1]) if "/" in path else ""


@router.post("/folders/create", response_class=HTMLResponse)
def create(request: Request,
           parent_path: str = Form(""),
           name: str = Form("")):
    try:
        parent = folders_module.validate_folder_path(parent_path)
        leaf = folders_module.validate_folder_name(name)
    except ValueError as e:
        return tree_error(request, str(e))
    target = f"{parent}/{leaf}" if parent else leaf
    if fs.folder_exists(target):
        return tree_error(request, f"'{target}' already exists.")
    for root in (fs.DATA_DIR, fs.TRANSCRIPTS_DIR, fs.INFORMATION_DIR):
        (root / target).mkdir(parents=True, exist_ok=True)
    return render_tree_partial(request)


@router.post("/folders/rename", response_class=HTMLResponse)
def rename(request: Request,
           path: str = Form(""),
           new_name: str = Form("")):
    try:
        src = folders_module.validate_folder_path(path)
    except ValueError as e:
        return tree_error(request, str(e))
    if not src:
        return tree_error(request, "Cannot rename the root folder.")
    try:
        leaf = folders_module.validate_folder_name(new_name)
    except ValueError as e:
        return tree_error(request, str(e))
    if src == "_inbox" or src.startswith("_inbox/"):
        return tree_error(request, "'_inbox' is managed by the app.")
    parent = _parent_of(src)
    target = f"{parent}/{leaf}" if parent else leaf
    if target == src:
        return render_tree_partial(request)
    if fs.folder_exists(target):
        return tree_error(request, f"'{target}' already exists.")
    try:
        stems = fs.move_folder_tree(src, target)
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        return tree_error(request, str(e))
    for stem in stems:
        try:
            search.reindex_meeting(stem)
        except Exception:
            _log.exception("reindex failed for %s", stem)
    return render_tree_partial(request)


@router.post("/folders/delete", response_class=HTMLResponse)
def delete(request: Request, path: str = Form("")):
    try:
        src = folders_module.validate_folder_path(path)
    except ValueError as e:
        return tree_error(request, str(e))
    if not src:
        return tree_error(request, "Cannot delete the root folder.")
    if src == "_inbox" or src.startswith("_inbox/"):
        return tree_error(request, "'_inbox' is managed by the app.")
    if not fs.folder_exists(src):
        return tree_error(request, f"'{src}' does not exist.")
    if not fs.folder_is_empty(src):
        return tree_error(request, f"'{src}' is not empty — move contents out first.")
    for root in (fs.DATA_DIR, fs.TRANSCRIPTS_DIR, fs.INFORMATION_DIR):
        p = root / src
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                return tree_error(request, f"'{src}' became non-empty during delete.")
    return render_tree_partial(request)


@router.post("/folders/move", response_class=HTMLResponse)
def move(request: Request,
         path: str = Form(""),
         new_parent_path: str = Form("")):
    try:
        src = folders_module.validate_folder_path(path)
        new_parent = folders_module.validate_folder_path(new_parent_path)
    except ValueError as e:
        return tree_error(request, str(e))
    if not src:
        return tree_error(request, "Cannot move the root folder.")
    if src == "_inbox" or src.startswith("_inbox/"):
        return tree_error(request, "'_inbox' is managed by the app.")
    if new_parent == src or new_parent.startswith(src + "/"):
        return tree_error(request, f"Can't move '{src}' into its own descendant (cycle).")
    basename = src.split("/")[-1]
    target = f"{new_parent}/{basename}" if new_parent else basename
    if target == src:
        return render_tree_partial(request)
    if fs.folder_exists(target):
        return tree_error(request, f"'{target}' already exists.")
    # Collision check: every descendant stem must be unique at the destination.
    all_meetings = fs.list_meetings(include_inbox=True)
    moving = {m.stem for m in all_meetings
              if m.subdir == src or m.subdir.startswith(src + "/")}
    outside = {m.stem for m in all_meetings
               if not (m.subdir == src or m.subdir.startswith(src + "/"))}
    clash = moving & outside
    if clash:
        return tree_error(request, f"Stem '{next(iter(clash))}' already exists elsewhere — aborting move.")
    try:
        stems = fs.move_folder_tree(src, target)
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        return tree_error(request, str(e))
    for stem in stems:
        try:
            search.reindex_meeting(stem)
        except Exception:
            _log.exception("reindex failed for %s", stem)
    return render_tree_partial(request)
