// Drag-and-drop + hover-action delegation for the /meetings nested tree.
//
// Drag: every row with [data-move-kind] is draggable. Every .folder-group
//   element (summary + its expanded children) and the root
//   <ul class="tree-root-drop"> are drop targets. On drop we POST to
//   /folders/move or /meetings/{stem}/move and repaint the sidebar.
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
    if (!el) return;
    el.outerHTML = html;
    // fetch() swaps don't trigger htmx:afterSwap, so re-install listeners
    // on the new <aside class="tree"> ourselves.
    install();
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
    // Note: the `toggle-all` click is handled by base.html's global
    // handler (it also flips the button text between "Expand all" /
    // "Collapse all"). We only handle the folder-scoped actions here.
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === "create") promptCreate(btn.dataset.folderPath || "");
    else if (action === "rename") promptRename(btn.dataset.folderPath || "",
                                               btn.dataset.folderName || "");
  }

  function onDragStart(e) {
    const src = e.target.closest("[data-move-kind]");
    if (!src) return;
    e.dataTransfer.setData("application/x-transcribe-move", JSON.stringify({
      kind: src.dataset.moveKind,
      id: src.dataset.moveId,
    }));
    e.dataTransfer.effectAllowed = "move";
    document.querySelector(".tree")?.classList.add("drag-active");
  }

  function onDragEnd() {
    const tree = document.querySelector(".tree");
    if (!tree) return;
    tree.classList.remove("drag-active");
    tree.querySelectorAll(".drop-target").forEach(n => n.classList.remove("drop-target"));
  }

  function highlightNode(el) {
    // Deepest enclosing folder-group wins. Otherwise, any area inside .tree
    // that is NOT a folder-group counts as the root drop zone; we paint the
    // always-visible .tree-root-hint strip so the user has a clear target.
    if (!el) return null;
    const folder = el.closest(".folder-group");
    if (folder) return folder;
    if (el.closest(".tree")) {
      return document.querySelector(".tree .tree-root-hint");
    }
    return null;
  }

  function findDropTarget(el) {
    if (!el) return null;
    const folder = el.closest(".folder-group");
    if (folder) return { kind: "folder", path: folder.dataset.folderPath };
    // Any area inside .tree that isn't a folder-group is a root drop.
    if (el.closest(".tree")) return { kind: "folder", path: "" };
    return null;
  }

  function onDragOver(e) {
    const tgt = findDropTarget(e.target);
    if (!tgt) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const node = highlightNode(e.target);
    if (node) node.classList.add("drop-target");
  }

  function onDragLeave(e) {
    // dragleave fires when crossing between descendants; only clear when
    // actually leaving the highlighted node.
    const node = highlightNode(e.target);
    if (node && !node.contains(e.relatedTarget)) {
      node.classList.remove("drop-target");
    }
  }

  async function onDrop(e) {
    const tgt = findDropTarget(e.target);
    if (!tgt) return;
    e.preventDefault();
    // Clear any lingering drop-target classes in the tree.
    document.querySelectorAll(".drop-target").forEach(n => n.classList.remove("drop-target"));
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
    tree.addEventListener("dragend", onDragEnd);
    tree.addEventListener("dragover", onDragOver);
    tree.addEventListener("dragleave", onDragLeave);
    tree.addEventListener("drop", onDrop);
  }

  document.addEventListener("DOMContentLoaded", install);
  // HTMX replaces <aside class="tree"> — re-install listeners after swaps.
  document.addEventListener("htmx:afterSwap", install);
})();
