// Drag-and-drop + hover-action delegation for the /meetings nested tree.
//
// Drag: every row with [data-move-kind] is draggable. Every folder <summary>
//   and the root <ul class="tree-root-drop"> are drop targets. On drop we
//   POST to /folders/move or /meetings/{stem}/move and repaint the sidebar.
//
// Hover actions: the ➕ (create) and ✏️ (rename) buttons carry
//   [data-action] + [data-folder-*] attrs; a single delegated click listener
//   prompts for a name and POSTs.
(function () {

  async function postForm(url, fields) {
    const body = new URLSearchParams();
    for (const [k, v] of Object.entries(fields)) body.set(k, v);
    const resp = await fetch(url, { method: "POST", body });
    const html = await resp.text();
    if (!html.includes('class="tree"')) return;  // unexpected response shape
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

  function onButtonClick(e) {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const path = btn.dataset.folderPath || "";
    const name = btn.dataset.folderName || "";
    if (btn.dataset.action === "create") promptCreate(path);
    else if (btn.dataset.action === "rename") promptRename(path, name);
  }

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
    if (folderSummary) {
      return { kind: "folder", path: folderSummary.parentElement.dataset.folderPath };
    }
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
    try {
      payload = JSON.parse(e.dataTransfer.getData("application/x-transcribe-move"));
    } catch {
      return;
    }
    // Client-side guards.
    // Cycle: folder moved into its own descendant.
    if (payload.kind === "folder"
        && (tgt.path === payload.id || tgt.path.startsWith(payload.id + "/"))) {
      return;
    }
    // No-op: meeting dropped on its own current parent.
    // (We don't know the source's current parent from the client without
    // another attribute — skip this micro-optimization. The server's
    // if m.subdir == target: early-return handles it.)

    let url, body;
    if (payload.kind === "folder") {
      url = "/folders/move";
      body = { path: payload.id, new_parent_path: tgt.path };
    } else {
      url = "/meetings/" + encodeURIComponent(payload.id) + "/move";
      body = { new_subdir: tgt.path };
    }
    await postForm(url, body);
  }

  function install() {
    const tree = document.querySelector(".tree");
    if (!tree) return;
    tree.addEventListener("click", onButtonClick);
    tree.addEventListener("dragstart", onDragStart);
    tree.addEventListener("dragover", onDragOver);
    tree.addEventListener("dragleave", onDragLeave);
    tree.addEventListener("drop", onDrop);
  }

  document.addEventListener("DOMContentLoaded", install);
  // HTMX replaces <aside class="tree"> — re-install listeners after swaps.
  document.addEventListener("htmx:afterSwap", install);
})();
