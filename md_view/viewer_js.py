"""The viewer script that runs in every page (navigation, find, sidebar, the bridge calls)."""

from __future__ import annotations

VIEWER_JS = r"""
(function () {
  "use strict";
  var CFG = window.__MDV__;
  var bridgeKey = (function () {
    var hash = window.location.hash;
    if (!/^#[A-Za-z0-9_-]{43}$/.test(hash)) return "";
    // Keep the key in this page's closure, out of the browser history URL.
    try { window.history.replaceState(null, "", window.location.href.split("#")[0]); }
    catch (err) { return ""; }
    return hash.slice(1);
  })();
  var STEPS = CFG.steps;
  var scroller = document.getElementById("scroller");
  var content  = document.getElementById("content");
  var img      = document.getElementById("imgview");
  var label    = document.getElementById("zoomLabel");
  var toastEl  = document.getElementById("toast");
  var mode     = CFG.mode;                 // doc | mermaid | image | blank
  var zoom     = CFG.zoom || 1;
  var fitMode  = mode === "image" && CFG.fit !== false;
  var natural  = { w: 0, h: 0 };
  var toastTimer = null;

  /* ------------------------------------------------------------------ */
  /* zoom                                                               */
  /* ------------------------------------------------------------------ */

  function clamp(z) { return Math.min(STEPS[STEPS.length - 1], Math.max(STEPS[0], z)); }

  function nearestStep(z, dir) {
    if (dir > 0) {
      for (var i = 0; i < STEPS.length; i++) if (STEPS[i] > z + 1e-4) return STEPS[i];
      return STEPS[STEPS.length - 1];
    }
    for (var j = STEPS.length - 1; j >= 0; j--) if (STEPS[j] < z - 1e-4) return STEPS[j];
    return STEPS[0];
  }

  function fitZoom() {
    if (!natural.w || !natural.h) return 1;
    var pad = 32;
    var sx = (scroller.clientWidth - pad) / natural.w;
    var sy = (scroller.clientHeight - pad) / natural.h;
    var z = Math.min(sx, sy);
    if (!CFG.vector) z = Math.min(1, z);     // never upscale raster art in fit mode
    return clamp(z > 0 ? z : 1);
  }

  function render(anchor) {
    if (mode === "image") {
      if (!natural.w) return;
      var before = anchor || {
        x: scroller.clientWidth / 2, y: scroller.clientHeight / 2,
        rx: (scroller.scrollLeft + scroller.clientWidth / 2) / Math.max(1, img.offsetWidth),
        ry: (scroller.scrollTop + scroller.clientHeight / 2) / Math.max(1, img.offsetHeight)
      };
      img.style.width = Math.round(natural.w * zoom) + "px";
      img.style.height = Math.round(natural.h * zoom) + "px";
      var fits = img.offsetWidth <= scroller.clientWidth &&
                 img.offsetHeight <= scroller.clientHeight;
      scroller.classList.toggle("fits", fits);
      if (!fits) {
        scroller.scrollLeft = before.rx * img.offsetWidth - before.x;
        scroller.scrollTop  = before.ry * img.offsetHeight - before.y;
      }
    } else {
      // Keep whatever sits under the anchor (the pointer, or the middle of the
      // view) where it is. Not on the first paint: the saved scroll position
      // is restored after that.
      var previous = parseFloat(content.style.zoom || "0");
      var keep = previous && previous !== zoom
        ? holdPoint(anchor || { x: scroller.clientWidth / 2, y: scroller.clientHeight / 2 })
        : null;
      content.style.zoom = zoom;
      if (keep) keep();
    }
    updateLabel();
  }

  /* The element that scrolls sideways for `el`: a wide diagram, table or code
     block scrolls inside its own box; everything else scrolls the page. */
  function scrollBoxX(el) {
    for (var node = el; node && node !== scroller; node = node.parentElement) {
      if (node.scrollWidth > node.clientWidth + 1) {
        var ox = getComputedStyle(node).overflowX;
        if (ox === "auto" || ox === "scroll") return node;
      }
    }
    return scroller;
  }

  /* Remember the element under a point (scroller coordinates) and where in it
     the point falls; the returned function scrolls it back under the point.
     An element rather than a page fraction, because text reflows as it
     zooms and the page height changes unevenly. */
  function holdPoint(a) {
    var sr = scroller.getBoundingClientRect();
    var x = sr.left + a.x, y = sr.top + a.y;
    var el = document.elementFromPoint(x, y);
    if (!el || !content.contains(el)) el = content;
    var r = el.getBoundingClientRect();
    var fx = (x - r.left) / Math.max(1, r.width);
    var fy = (y - r.top) / Math.max(1, r.height);
    return function () {
      var n = el.getBoundingClientRect();
      var dx = n.left + fx * n.width - x, dy = n.top + fy * n.height - y;
      var box = scrollBoxX(el), before = box.scrollLeft;
      box.scrollLeft += dx;
      if (box !== scroller) scroller.scrollLeft += dx - (box.scrollLeft - before);
      scroller.scrollTop += dy;
    };
  }

  function updateLabel() {
    var pct = Math.round(zoom * 100);
    label.textContent = (fitMode ? "Fit" : pct + "%");
    label.title = pct + "% - click to reset to 100%";
    var minus = document.getElementById("zoomOut"), plus = document.getElementById("zoomIn");
    if (minus) minus.disabled = zoom <= STEPS[0] + 1e-4;
    if (plus) plus.disabled = zoom >= STEPS[STEPS.length - 1] - 1e-4;
  }

  function toast(text) {
    if (!toastEl) return;
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 900);
  }

  function setZoom(z, opts) {
    opts = opts || {};
    fitMode = false;
    zoom = clamp(z);
    render(opts.anchor);
    if (!opts.silent) toast(Math.round(zoom * 100) + "%");
    persist();
  }

  function step(dir, anchor) { setZoom(nearestStep(zoom, dir), { anchor: anchor }); }

  function doFit() {
    if (mode !== "image") { setZoom(1); return; }
    fitMode = true;
    zoom = fitZoom();
    render();
    toast("Fit");
    persist();
  }

  function resetZoom() { setZoom(1); }

  var persistTimer = null;
  function persist() {
    clearTimeout(persistTimer);
    persistTimer = setTimeout(function () {
      call("save_view_prefs", {
        zoom: zoom, style: document.documentElement.dataset.style,
        fit: fitMode, mode: mode
      });
    }, 400);
  }

  /* ------------------------------------------------------------------ */
  /* image setup + panning                                              */
  /* ------------------------------------------------------------------ */

  if (mode === "image" && img) {
    var ready = function () {
      // CFG.viewBox is set only when the file itself declares no absolute size,
      // in which case the engine's naturalWidth is a placeholder (see
      // svg_dimensions in md-view.py).
      if (CFG.viewBox) {
        natural.w = CFG.viewBox[0];
        natural.h = CFG.viewBox[1];
      } else {
        natural.w = img.naturalWidth || 800;
        natural.h = img.naturalHeight || 600;
      }
      img.dataset.naturalWidth = natural.w;
      img.dataset.naturalHeight = natural.h;
      if (fitMode) { zoom = fitZoom(); }
      render();
      var d = document.getElementById("dims");
      if (d) d.textContent = Math.round(natural.w) + " × " + Math.round(natural.h);
    };
    if (img.complete && img.naturalWidth) ready(); else img.addEventListener("load", ready);
    img.addEventListener("error", function () {
      document.getElementById("scroller").innerHTML =
        '<div class="mdv-center"><div class="inner"><div class="glyph">&#9888;</div>' +
        "<h1>Cannot display this image</h1><p>The file may be corrupt or in an " +
        "unsupported format.</p></div></div>";
    });

    var pan = null;
    scroller.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 || scroller.classList.contains("fits")) return;
      pan = { x: e.clientX, y: e.clientY, sl: scroller.scrollLeft, st: scroller.scrollTop };
      scroller.classList.add("panning");
      scroller.setPointerCapture(e.pointerId);
    });
    scroller.addEventListener("pointermove", function (e) {
      if (!pan) return;
      scroller.scrollLeft = pan.sl - (e.clientX - pan.x);
      scroller.scrollTop  = pan.st - (e.clientY - pan.y);
    });
    var endPan = function () { pan = null; scroller.classList.remove("panning"); };
    scroller.addEventListener("pointerup", endPan);
    scroller.addEventListener("pointercancel", endPan);
    scroller.addEventListener("dblclick", function () {
      if (fitMode) setZoom(1); else doFit();
    });
    window.addEventListener("resize", function () { if (fitMode) { zoom = fitZoom(); render(); } });
  }

  /* ------------------------------------------------------------------ */
  /* the unzoomed page width, for github-ext's magnifying zoom          */
  /* ------------------------------------------------------------------ */

  /* The scroller is not zoomed, so its width is the window's width at 100%.
     #content takes it as its own width in github-ext (see the stylesheet). */
  function updateViewWidth() {
    content.style.setProperty("--view-w", scroller.clientWidth + "px");
  }
  if (content && scroller) {
    updateViewWidth();
    if (window.ResizeObserver) new ResizeObserver(updateViewWidth).observe(scroller);
    else window.addEventListener("resize", updateViewWidth);
  }

  /* ------------------------------------------------------------------ */
  /* drag to pan documents and diagrams                                 */
  /* ------------------------------------------------------------------ */

  /* True when (x, y) is over an actual character, so a drag there should
     select text rather than pan. Whitespace beside or between blocks pans. */
  function overText(x, y) {
    if (!document.caretRangeFromPoint) return false;
    var hit = document.caretRangeFromPoint(x, y);
    if (!hit || hit.startContainer.nodeType !== 3) return false;
    var node = hit.startContainer, probe = document.createRange();
    var from = Math.max(0, hit.startOffset - 1);
    var to = Math.min(node.length - 1, hit.startOffset);
    for (var i = from; i <= to; i++) {
      probe.setStart(node, i); probe.setEnd(node, i + 1);
      var rects = probe.getClientRects();
      for (var j = 0; j < rects.length; j++) {
        var b = rects[j];
        if (x >= b.left - 1 && x <= b.right + 1 && y >= b.top - 1 && y <= b.bottom + 1) {
          return true;
        }
      }
    }
    return false;
  }

  function canPan(e) {
    var t = e.target;
    if (!t || !t.closest || t.closest("a, button, input, textarea, select, summary, label")) {
      return false;
    }
    // A press on a scrollbar belongs to the scrollbar. Measured on screen:
    // inside zoomed content, client sizes are unzoomed but the pointer is not.
    if (t.clientWidth && (t.offsetWidth > t.clientWidth + t.clientLeft
                          || t.offsetHeight > t.clientHeight + t.clientTop)) {
      var box = t.getBoundingClientRect(), scale = box.width / Math.max(1, t.offsetWidth);
      if (e.clientX - box.left > (t.clientLeft + t.clientWidth) * scale ||
          e.clientY - box.top > (t.clientTop + t.clientHeight) * scale) return false;
    }
    if (t.closest("pre.mermaid svg, svg, img")) return true;  // pictures always pan
    return mode === "mermaid" || !overText(e.clientX, e.clientY);
  }

  if (mode === "doc" || mode === "mermaid") {
    var drag = null, swallowClick = false;
    scroller.addEventListener("mousedown", function (e) {
      swallowClick = false;            // a new press starts a new gesture
      if (e.button !== 0 || e.detail > 1 || !canPan(e)) return;
      e.preventDefault();              // no text selection, no native svg drag
      drag = { x: e.clientX, y: e.clientY, moved: false,
               box: scrollBoxX(e.target), sl: 0, st: scroller.scrollTop };
      drag.sl = drag.box.scrollLeft;
      drag.pageSl = scroller.scrollLeft;
    });
    window.addEventListener("mousemove", function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved) {
        if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;   // still a click
        drag.moved = true;
        document.body.classList.add("dragging");
      }
      drag.box.scrollLeft = drag.sl - dx;
      if (drag.box !== scroller) scroller.scrollLeft = drag.pageSl - dx;
      scroller.scrollTop = drag.st - dy;
    });
    window.addEventListener("mouseup", function () {
      if (!drag) return;
      if (drag.moved) {
        swallowClick = true;           // a pan is not a click on what lies below
        setTimeout(function () { swallowClick = false; }, 0);
      } else {
        // A plain click on blank space clears a selection, as it normally would.
        var sel = window.getSelection();
        if (sel && !sel.isCollapsed) sel.removeAllRanges();
      }
      drag = null;
      document.body.classList.remove("dragging");
    });
    scroller.addEventListener("click", function (e) {
      if (swallowClick) { e.preventDefault(); e.stopPropagation(); swallowClick = false; }
    }, true);
  }

  /* ------------------------------------------------------------------ */
  /* wheel + keyboard                                                   */
  /* ------------------------------------------------------------------ */

  scroller.addEventListener("wheel", function (e) {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    var r = scroller.getBoundingClientRect();
    var anchor = null;
    if (mode === "image" && img && img.offsetWidth) {
      anchor = {
        x: e.clientX - r.left, y: e.clientY - r.top,
        rx: (scroller.scrollLeft + e.clientX - r.left) / img.offsetWidth,
        ry: (scroller.scrollTop + e.clientY - r.top) / img.offsetHeight
      };
    } else if (mode !== "image") {
      anchor = { x: e.clientX - r.left, y: e.clientY - r.top };   // zoom about the pointer
    }
    var factor = Math.exp(-e.deltaY * 0.0016);
    setZoom(zoom * factor, { anchor: anchor });
  }, { passive: false });

  document.addEventListener("keydown", function (e) {
    var ctrl = e.ctrlKey || e.metaKey;
    var target = e.target;
    var typing = !!target && (target.tagName === "INPUT"
                              || target.tagName === "TEXTAREA"
                              || target.isContentEditable);
    if (ctrl && e.key.toLowerCase() === "f") { e.preventDefault(); openFind(); return; }
    if (e.key === "F3") { e.preventDefault(); stepFind(e.shiftKey ? -1 : 1); return; }
    if (ctrl && (e.key === "+" || e.key === "=" || e.code === "NumpadAdd")) {
      e.preventDefault(); step(+1); return;
    }
    if (ctrl && (e.key === "-" || e.key === "_" || e.code === "NumpadSubtract")) {
      e.preventDefault(); step(-1); return;
    }
    if (ctrl && (e.key === "0" || e.code === "Numpad0")) { e.preventDefault(); resetZoom(); return; }
    if (ctrl && e.key.toLowerCase() === "o") { e.preventDefault(); call("pick_file"); return; }
    if (ctrl && e.key.toLowerCase() === "d") { e.preventDefault(); cycleStyle(); return; }
    if (ctrl && e.key.toLowerCase() === "b") { e.preventDefault(); toggleSidebar(); return; }
    if (ctrl && e.key.toLowerCase() === "t") { e.preventDefault(); call("new_tab"); return; }
    if (ctrl && e.key.toLowerCase() === "w") { e.preventDefault(); call("close_tab", -1); return; }
    if (ctrl && e.key === "Tab") {
      e.preventDefault();
      call(e.shiftKey ? "prev_tab" : "next_tab");
      return;
    }
    if (ctrl && e.key >= "1" && e.key <= "9") {
      e.preventDefault(); call("select_tab", parseInt(e.key, 10) - 1); return;
    }
    if (e.key === "F5" || (ctrl && e.key.toLowerCase() === "r")) {
      e.preventDefault(); call("refresh"); return;
    }
    if (e.key === "F11") { e.preventDefault(); call("toggle_fullscreen"); return; }
    if (e.key === "Escape") {
      if (anyMenuOpen()) { closeMenus(null); return; }
      if (findOpen()) { closeFind(); return; }
      return;
    }
    if (!ctrl && !e.altKey && !typing) {
      if (e.key === "f") { e.preventDefault(); doFit(); return; }
      // 1-4 pick a style directly; they also label the menu rows.
      if (e.key >= "1" && e.key <= String(STYLES.length)) {
        e.preventDefault();
        var picked = STYLES[parseInt(e.key, 10) - 1];
        applyStyle(picked);
        toast(picked.charAt(0).toUpperCase() + picked.slice(1));
        return;
      }
      if (e.key === "0") { e.preventDefault(); setZoom(1); return; }
      if (e.key === "+" || e.key === "=") { e.preventDefault(); step(+1); return; }
      if (e.key === "-") { e.preventDefault(); step(-1); return; }
      if (e.key === "[" || (e.key === "ArrowLeft" && e.altKey)) { e.preventDefault(); call("go_back"); return; }
      if (e.key === "]") { e.preventDefault(); call("go_forward"); return; }
      if (e.key === "w" && mode === "doc") {
        e.preventDefault(); document.body.classList.toggle("wide"); return;
      }
    }
    if (e.key === " " && mode === "image") {
      e.preventDefault(); scroller.scrollTop += scroller.clientHeight * 0.9;
    }
  });

  /* ------------------------------------------------------------------ */
  /* sidebar trees                                                      */
  /* ------------------------------------------------------------------ */

  var sidebar = document.getElementById("sidebar");
  var docsTree = document.getElementById("docsTree");
  var filesTree = document.getElementById("filesTree");

  function callAsync(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    var api = window.pywebview && window.pywebview.api;
    if (!bridgeKey || !api || typeof api.dispatch !== "function") return Promise.reject("no bridge");
    try { return Promise.resolve(api.dispatch(bridgeKey, name, args)); }
    catch (err) { return Promise.reject(err); }
  }

  /* Every expanded folder, so Python can restore the tree after a repaint.
     Keys rather than paths, so two roots showing one folder stay independent. */
  function expandedKeys() {
    return Array.prototype.map.call(
      filesTree ? filesTree.querySelectorAll(".node.open[data-dir='1']") : [],
      function (n) { return n.dataset.key; }
    );
  }

  /* Folders collapsed in the open-documents tree. */
  function collapsedDocPaths() {
    return Array.prototype.map.call(
      docsTree ? docsTree.querySelectorAll(".node[data-dir='1']:not(.open)") : [],
      function (n) { return n.dataset.path; }
    );
  }

  /* Sent straight away rather than debounced: clicking a file replaces the
     whole page, and a pending timer would die with it, losing the toggle. */
  function persistTree(kind) {
    if (kind === "files") call("set_expanded", expandedKeys());
    else call("set_doc_collapsed", collapsedDocPaths());
  }

  var KEY_SEP = "\u001f";

  function makeNode(item, depth, kind, rootId) {
    var node = document.createElement("div");
    node.className = "node";
    node.dataset.path = item.path || "";
    node.dataset.dir = item.dir ? "1" : "0";
    // Scoped by root: the same folder reached from two roots is two rows,
    // each with its own open/closed state.
    node.dataset.root = item.root || rootId || "";
    node.dataset.key = item.key || (node.dataset.root + KEY_SEP + node.dataset.path);

    var row = document.createElement("div");
    row.className = "row" + (item.dir ? " dir" : " file")
                  + (item.active ? " active" : "") + (item.stale ? " stale" : "");
    row.style.paddingLeft = (6 + depth * 12) + "px";
    row.title = item.path || item.name;
    if (typeof item.tab === "number") row.dataset.tab = item.tab;

    var chev = document.createElement("span");
    chev.className = "chev" + (item.dir ? "" : " leaf");
    chev.textContent = "▶";
    row.appendChild(chev);

    var ico = document.createElement("span");
    ico.className = "ico";
    ico.textContent = item.dir ? "\u{1F4C1}" : glyphFor(item.name);
    row.appendChild(ico);

    var nm = document.createElement("span");
    nm.className = "nm";
    nm.textContent = item.name;
    row.appendChild(nm);

    var dot = document.createElement("span");
    dot.className = "dot";
    row.appendChild(dot);

    // Open documents get a close button, mirroring the tab strip.
    if (kind === "docs" && !item.dir && typeof item.tab === "number") {
      var x = document.createElement("button");
      x.className = "x";
      x.type = "button";
      x.dataset.close = item.tab;
      x.title = "Close " + item.name;
      x.innerHTML = "&times;";
      row.appendChild(x);
    }

    node.appendChild(row);

    if (item.dir) {
      var kids = document.createElement("div");
      kids.className = "kids";
      node.appendChild(kids);
      if (item.children) {
        fillKids(kids, item.children, depth + 1, kind, item.more, node.dataset.root);
        node.dataset.loaded = "1";
        // Children are rendered even for a collapsed folder, so honour the flag.
        if (item.open !== false) node.classList.add("open");
      }
      if (item.open && !item.children) node.dataset.loaded = "";
    }
    return node;
  }

  function glyphFor(name) {
    var ext = (name.split(".").pop() || "").toLowerCase();
    if (ext === "mmd" || ext === "mermaid") return "◇";
    if (ext === "svg") return "◩";
    if (["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "apng", "avif"].indexOf(ext) >= 0) {
      return "▦";
    }
    return "▬";
  }

  function fillKids(container, children, depth, kind, more, rootId) {
    container.textContent = "";
    children.forEach(function (child) {
      container.appendChild(makeNode(child, depth, kind, rootId));
    });
    if (more) {
      var row = document.createElement("div");
      row.className = "row more";
      row.style.paddingLeft = (6 + depth * 12) + "px";
      row.textContent = "… " + more + " more";
      container.appendChild(row);
    }
  }

  function paintTree(container, nodes, kind, emptyText) {
    if (!container) return;
    container.textContent = "";
    if (!nodes || !nodes.length) {
      var msg = document.createElement("div");
      msg.className = "empty";
      msg.textContent = emptyText;
      container.appendChild(msg);
      return;
    }
    nodes.forEach(function (n) { container.appendChild(makeNode(n, 0, kind, n.root)); });
  }

  function depthOf(node) {
    var depth = 0, cursor = node.parentElement;
    while (cursor && cursor !== docsTree && cursor !== filesTree) {
      if (cursor.classList.contains("kids")) depth++;
      cursor = cursor.parentElement;
    }
    return depth;
  }

  function toggleDir(node, kind) {
    if (node.classList.contains("open")) {
      node.classList.remove("open");
      persistTree(kind);
      return;
    }
    if (node.dataset.loaded === "1") {
      node.classList.add("open");
      persistTree(kind);
      return;
    }
    var chev = node.querySelector(":scope > .row > .chev");
    if (chev) chev.classList.add("spin");
    callAsync("list_dir", node.dataset.path).then(function (result) {
      if (chev) chev.classList.remove("spin");
      var kids = node.querySelector(":scope > .kids");
      if (!kids) return;
      node.dataset.loaded = "1";
      var entries = (result && result.entries) || [];
      if (!entries.length) {
        kids.textContent = "";
        var row = document.createElement("div");
        row.className = "row " + (result && result.denied ? "denied" : "more");
        row.style.paddingLeft = (6 + (depthOf(node) + 1) * 12) + "px";
        row.textContent = result && result.denied ? "not readable" : "empty";
        kids.appendChild(row);
      } else {
        fillKids(kids, entries, depthOf(node) + 1, kind, result.more,
                 node.dataset.root);
      }
      node.classList.add("open");
      persistTree(kind);
    }, function () {
      if (chev) chev.classList.remove("spin");
    });
  }

  function wireTree(container, kind) {
    if (!container) return;
    container.addEventListener("click", function (e) {
      var closer = e.target.closest("button[data-close]");
      if (closer) {
        e.stopPropagation();
        call("close_tab", parseInt(closer.dataset.close, 10));
        return;
      }
      var row = e.target.closest(".row");
      if (!row || row.classList.contains("more") || row.classList.contains("denied")) return;
      var node = row.parentElement;
      if (row.classList.contains("dir")) { toggleDir(node, kind); return; }
      if (kind === "docs") {
        if (row.dataset.tab !== undefined) call("select_tab", parseInt(row.dataset.tab, 10));
      } else {
        call("open_from_tree", node.dataset.path);
      }
    });
    container.addEventListener("dblclick", function (e) {
      // Double-clicking a folder name should not select text.
      if (e.target.closest(".row.dir")) e.preventDefault();
    });
  }

  paintTree(docsTree, CFG.docsTree, "docs", "No documents open.");
  paintTree(filesTree, CFG.filesTree, "files", "No drives available.");
  wireTree(docsTree, "docs");
  wireTree(filesTree, "files");

  var docsCount = document.getElementById("docsCount");
  if (docsCount) docsCount.textContent = CFG.tabCount ? String(CFG.tabCount) : "";

  /* keep the active document visible in the open-documents tree */
  var activeRow = docsTree && docsTree.querySelector(".row.active");
  if (activeRow && activeRow.scrollIntoView) {
    activeRow.scrollIntoView({ block: "nearest" });
  }

  /* ---- pane collapse ---- */
  function applyPanes(state) {
    ["docs", "files"].forEach(function (name) {
      var pane = document.getElementById(name === "docs" ? "paneDocs" : "paneFiles");
      if (pane) pane.classList.toggle("collapsed", state[name] === false);
    });
  }
  var paneState = { docs: CFG.panes.docs !== false, files: CFG.panes.files !== false };
  applyPanes(paneState);

  on("revealBtn", function (e) {
    e.stopPropagation();          // do not collapse the pane we are revealing in
    call("reveal_active");
  });

  Array.prototype.forEach.call(document.querySelectorAll(".pane > header"), function (h) {
    h.addEventListener("click", function (e) {
      if (e.target.closest(".reveal")) return;
      var name = h.dataset.pane;
      paneState[name] = !paneState[name];
      applyPanes(paneState);
      call("set_sidebar", !document.body.classList.contains("no-sidebar"),
           currentWidth(), paneState, currentDocsHeight());
    });
  });

  /* ---- show / hide ---- */
  function currentWidth() {
    var raw = document.body.style.getPropertyValue("--sidebar-w");
    return parseInt(raw, 10) || CFG.sidebarWidth || 264;
  }

  function currentDocsHeight() {
    var raw = document.body.style.getPropertyValue("--docs-h");
    return parseInt(raw, 10) || CFG.docsHeight || 220;
  }

  /* ---- the separator between the two trees ---- */
  var paneGrip = document.getElementById("paneGrip");
  if (paneGrip && sidebar) {
    var vdrag = null;
    paneGrip.addEventListener("pointerdown", function (e) {
      var docsPane = document.getElementById("paneDocs");
      if (!docsPane || docsPane.classList.contains("collapsed")) return;
      vdrag = { y: e.clientY, h: docsPane.offsetHeight };
      paneGrip.classList.add("dragging");
      paneGrip.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    paneGrip.addEventListener("pointermove", function (e) {
      if (!vdrag) return;
      // Leave room for the Computer pane's own header and a few rows.
      var ceiling = Math.max(80, sidebar.clientHeight - 120);
      var next = Math.max(60, Math.min(ceiling, vdrag.h + (e.clientY - vdrag.y)));
      document.body.style.setProperty("--docs-h", next + "px");
    });
    var endVDrag = function () {
      if (!vdrag) return;
      vdrag = null;
      paneGrip.classList.remove("dragging");
      call("set_sidebar", !document.body.classList.contains("no-sidebar"),
           currentWidth(), paneState, currentDocsHeight());
    };
    paneGrip.addEventListener("pointerup", endVDrag);
    paneGrip.addEventListener("pointercancel", endVDrag);
    paneGrip.addEventListener("dblclick", function () {
      document.body.style.setProperty("--docs-h", "220px");   // back to the default
      call("set_sidebar", !document.body.classList.contains("no-sidebar"),
           currentWidth(), paneState, 220);
    });
  }

  function toggleSidebar() {
    var hidden = document.body.classList.toggle("no-sidebar");
    call("set_sidebar", !hidden, currentWidth(), paneState, currentDocsHeight());
    if (mode === "image" && fitMode) { zoom = fitZoom(); render(); }
  }
  on("sidebarBtn", toggleSidebar);

  /* ---- resize ---- */
  var grip = document.getElementById("sideResize");
  if (grip) {
    var drag = null;
    grip.addEventListener("pointerdown", function (e) {
      drag = { x: e.clientX, w: currentWidth() };
      grip.classList.add("dragging");
      grip.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    grip.addEventListener("pointermove", function (e) {
      if (!drag) return;
      var next = Math.max(160, Math.min(640, drag.w + (e.clientX - drag.x)));
      document.body.style.setProperty("--sidebar-w", next + "px");
    });
    var endDrag = function () {
      if (!drag) return;
      drag = null;
      grip.classList.remove("dragging");
      call("set_sidebar", !document.body.classList.contains("no-sidebar"),
           currentWidth(), paneState, currentDocsHeight());
      if (mode === "image" && fitMode) { zoom = fitZoom(); render(); }
    };
    grip.addEventListener("pointerup", endDrag);
    grip.addEventListener("pointercancel", endDrag);
  }

  /* ------------------------------------------------------------------ */
  /* find in document                                                   */
  /* ------------------------------------------------------------------ */

  var findBar = document.getElementById("findbar");
  var findInput = document.getElementById("findInput");
  var findCount = document.getElementById("findCount");
  var findRanges = [];
  var findIndex = -1;
  var findTimer = null;
  var FIND_CAP = 5000;
  var CAN_HIGHLIGHT = typeof CSS !== "undefined" && !!CSS.highlights &&
                      typeof Highlight === "function";

  /* Ranges over the document's text, one per occurrence. A match straddling two
     text nodes (bold in the middle of a phrase) is not found: spanning them would
     mean rewriting the tree, which is exactly what this approach avoids. */
  function collectMatches(query) {
    var out = [];
    if (!query || !CAN_HIGHLIGHT || !content) return out;
    var needle = query.toLowerCase();
    var walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (!node.data) return NodeFilter.FILTER_REJECT;
        var parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        var tag = parent.tagName;
        if (tag === "SCRIPT" || tag === "STYLE") return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var node;
    while ((node = walker.nextNode())) {
      var hay = node.data.toLowerCase();
      var at = hay.indexOf(needle);
      while (at >= 0) {
        var range = document.createRange();
        range.setStart(node, at);
        range.setEnd(node, at + needle.length);
        out.push(range);
        if (out.length >= FIND_CAP) return out;
        at = hay.indexOf(needle, at + needle.length);
      }
    }
    return out;
  }

  function paintMatches() {
    if (!CAN_HIGHLIGHT) return;
    CSS.highlights.delete("mdv-find");
    CSS.highlights.delete("mdv-find-current");
    if (!findRanges.length) return;
    var rest = new Highlight();
    findRanges.forEach(function (r, i) { if (i !== findIndex) rest.add(r); });
    CSS.highlights.set("mdv-find", rest);
    if (findIndex >= 0 && findRanges[findIndex]) {
      // The current match sits in its own highlight, so it always paints on top.
      CSS.highlights.set("mdv-find-current", new Highlight(findRanges[findIndex]));
    }
  }

  function updateFindCount() {
    if (!findCount || !findInput) return;
    var hasQuery = !!findInput.value;
    findBar.classList.toggle("none", hasQuery && findRanges.length === 0);
    findCount.textContent = !hasQuery ? ""
      : findRanges.length ? (findIndex + 1) + " / " + findRanges.length
      : "0 / 0";
    var prev = document.getElementById("findPrev");
    var next = document.getElementById("findNext");
    if (prev) prev.disabled = findRanges.length < 1;
    if (next) next.disabled = findRanges.length < 1;
  }

  function scrollToMatch() {
    if (findIndex < 0 || !findRanges[findIndex] || !scroller) return;
    var rect = findRanges[findIndex].getBoundingClientRect();
    if (!rect || (!rect.width && !rect.height)) return;
    var box = scroller.getBoundingClientRect();
    var margin = 56;
    if (rect.top < box.top + margin || rect.bottom > box.bottom - margin) {
      scroller.scrollTop += (rect.top - box.top) - scroller.clientHeight / 3;
    }
    if (rect.left < box.left + 8 || rect.right > box.right - 8) {
      scroller.scrollLeft += (rect.left - box.left) - scroller.clientWidth / 3;
    }
  }

  function runFind(fromStart) {
    if (!findInput) return;
    findRanges = collectMatches(findInput.value);
    if (!findRanges.length) findIndex = -1;
    else if (fromStart || findIndex < 0 || findIndex >= findRanges.length) findIndex = 0;
    paintMatches();
    updateFindCount();
    if (findIndex >= 0) scrollToMatch();
  }

  function stepFind(delta) {
    if (!findRanges.length) return;
    findIndex = (findIndex + delta + findRanges.length) % findRanges.length;
    paintMatches();
    updateFindCount();
    scrollToMatch();
  }

  function findOpen() {
    return !!findBar && !findBar.hidden;
  }

  function openFind() {
    if (!findBar || mode === "image" || mode === "blank") return;
    findBar.hidden = false;
    findInput.focus();
    findInput.select();
    if (findInput.value) runFind(true); else updateFindCount();
  }

  function closeFind() {
    if (!findBar) return;
    findBar.hidden = true;
    if (CAN_HIGHLIGHT) {
      CSS.highlights.delete("mdv-find");
      CSS.highlights.delete("mdv-find-current");
    }
    findRanges = [];
    findIndex = -1;
    findBar.classList.remove("none");
    call("set_find_query", findInput ? findInput.value : "");
  }

  if (findInput) {
    if (CFG.findQuery) findInput.value = CFG.findQuery;
    findInput.addEventListener("input", function () {
      clearTimeout(findTimer);
      findTimer = setTimeout(function () { runFind(true); }, 90);
    });
    findInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); stepFind(e.shiftKey ? -1 : 1); }
      else if (e.key === "Escape") { e.preventDefault(); closeFind(); }
    });
  }
  on("findBtn", openFind);
  on("findPrev", function () { stepFind(-1); });
  on("findNext", function () { stepFind(1); });
  on("findClose", closeFind);

  /* test hook */
  window.__mdv_find = {
    open: openFind, close: closeFind, step: stepFind, run: runFind,
    state: function () {
      return { open: findOpen(), total: findRanges.length, index: findIndex,
               label: findCount ? findCount.textContent : "",
               supported: CAN_HIGHLIGHT };
    }
  };

  /* ------------------------------------------------------------------ */
  /* tabs                                                               */
  /* ------------------------------------------------------------------ */

  var tabStrip = document.getElementById("tabs");
  if (tabStrip) {
    tabStrip.addEventListener("click", function (e) {
      var closer = e.target.closest("button[data-close]");
      if (closer) {
        e.stopPropagation();
        call("close_tab", parseInt(closer.dataset.close, 10));
        return;
      }
      if (e.target.closest("#newTab")) { call("new_tab"); return; }
      var tab = e.target.closest(".tab[data-index]");
      if (tab) call("select_tab", parseInt(tab.dataset.index, 10));
    });
    // Middle-click closes, as it does everywhere else.
    tabStrip.addEventListener("auxclick", function (e) {
      if (e.button !== 1) return;
      var tab = e.target.closest(".tab[data-index]");
      if (tab) { e.preventDefault(); call("close_tab", parseInt(tab.dataset.index, 10)); }
    });
    // Keep the active tab in view when the strip overflows.
    var sel = tabStrip.querySelector('.tab[aria-selected="true"]');
    if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  /* ------------------------------------------------------------------ */
  /* link handling: local docs open in-app, the web opens in the browser */
  /* ------------------------------------------------------------------ */

  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    var href = a.getAttribute("href") || "";
    e.preventDefault();
    if (href.charAt(0) === "#") {
      // <base> would resolve a bare "#x" to the document's folder and navigate there.
      var id = href.slice(1), t = null;
      try { id = decodeURIComponent(id); } catch (err) { /* keep the raw text */ }
      if (id) t = document.getElementById(id) || document.getElementsByName(id)[0];
      if (t) t.scrollIntoView();
      else if (!id) scroller.scrollTop = 0;
      return;
    }
    if (/^(https?|ftp|mailto):/i.test(href)) { call("open_external", href); }
    else { call("open_path", a.href || href); }
  });

  /* ------------------------------------------------------------------ */
  /* style menu                                                         */
  /* ------------------------------------------------------------------ */

  var STYLES = CFG.styles || ["light", "dark", "github", "github-ext"];
  var FONTS = CFG.fonts || ["system", "sans", "serif", "mono"];
  var MERMAID_THEME = { light: "neutral", dark: "dark", github: "default",
                        "github-ext": "default" };

  function currentStyle() {
    return document.documentElement.dataset.style || STYLES[0];
  }

  function currentFont() {
    return document.documentElement.dataset.font || FONTS[0];
  }

  /* Mark the chosen row in a menu. */
  function markMenu(menuEl, value) {
    if (!menuEl) return;
    menuEl.querySelectorAll("button[data-value]").forEach(function (b) {
      b.setAttribute("aria-checked", b.dataset.value === value ? "true" : "false");
    });
  }

  function applyStyle(name, opts) {
    if (STYLES.indexOf(name) < 0) return;
    document.documentElement.dataset.style = name;
    markMenu(document.getElementById("styleMenu"), name);
    var btn = document.getElementById("styleBtn");
    if (btn) btn.title = "Style: " + name + " (Ctrl+D cycles)";
    renderMermaid(name);
    if (!(opts && opts.silent)) persist();
  }
  window.__mdv_setStyle = applyStyle;

  /* Font is pure CSS: swap the attribute, no repaint, no re-render. */
  function applyFont(name, opts) {
    if (FONTS.indexOf(name) < 0) return;
    document.documentElement.dataset.font = name;
    markMenu(document.getElementById("fontMenu"), name);
    var btn = document.getElementById("fontBtn");
    if (btn) btn.title = "Font: " + name;
    if (!(opts && opts.silent)) {
      call("set_font", name);
      if (mode === "image" && fitMode) { zoom = fitZoom(); render(); }
    }
  }
  window.__mdv_setFont = applyFont;

  function cycleStyle() {
    var next = STYLES[(STYLES.indexOf(currentStyle()) + 1) % STYLES.length];
    applyStyle(next);
    toast(next.charAt(0).toUpperCase() + next.slice(1));
  }

  /* ---- generic popup menus ---- */

  function closeMenus(except) {
    Array.prototype.forEach.call(document.querySelectorAll(".menu"), function (m) {
      if (m === except) return;
      m.hidden = true;
      var owner = document.querySelector('[data-menu="' + m.id + '"]');
      if (owner) owner.setAttribute("aria-expanded", "false");
    });
  }

  function openMenu(menuEl, open) {
    if (!menuEl) return;
    var owner = document.querySelector('[data-menu="' + menuEl.id + '"]');
    var show = open === undefined ? menuEl.hidden : open;
    if (show) closeMenus(menuEl);
    menuEl.hidden = !show;
    if (owner) owner.setAttribute("aria-expanded", show ? "true" : "false");
    if (show) {
      var active = menuEl.querySelector('button[aria-checked="true"]') ||
                   menuEl.querySelector("button[data-value]");
      if (active) active.focus();
    }
  }

  function applyChoice(kind, value) {
    if (kind === "style") applyStyle(value);
    else if (kind === "font") applyFont(value);
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-menu]"), function (btn) {
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      openMenu(document.getElementById(btn.dataset.menu));
    });
  });

  Array.prototype.forEach.call(document.querySelectorAll(".menu"), function (menuEl) {
    menuEl.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-value]");
      if (!b) return;
      applyChoice(menuEl.dataset.kind, b.dataset.value);
      openMenu(menuEl, false);
      var owner = document.querySelector('[data-menu="' + menuEl.id + '"]');
      if (owner) owner.focus();
    });
    menuEl.addEventListener("keydown", function (e) {
      var items = Array.prototype.slice.call(menuEl.querySelectorAll("button[data-value]"));
      var at = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        var next = (at + (e.key === "ArrowDown" ? 1 : items.length - 1) + items.length)
                   % items.length;
        items[next].focus();
      }
    });
  });

  document.addEventListener("click", function (e) {
    if (!e.target.closest(".menu-wrap")) closeMenus(null);
  });

  function anyMenuOpen() {
    return !!document.querySelector(".menu:not([hidden])");
  }

  /* ---- csv column alignment ---- */
  on("alignBtn", function () {
    var btn = document.getElementById("alignBtn");
    if (btn) btn.setAttribute("aria-pressed",
      btn.getAttribute("aria-pressed") === "true" ? "false" : "true");
    call("toggle_csv_align");
  });

  /* ------------------------------------------------------------------ */
  /* mermaid                                                            */
  /* ------------------------------------------------------------------ */

  function renderMermaid(styleName) {
    var nodes = document.querySelectorAll("pre.mermaid");
    if (!nodes.length) return;
    if (typeof window.mermaid === "undefined") {
      nodes.forEach(function (n) {
        if (n.dataset.failed) return;
        n.dataset.failed = "1";
        call("mermaid_missing");
        n.innerHTML = '<span class="mdv-nomermaid">Mermaid renderer unavailable - run ' +
                      "<code>md-view.py --fetch-assets</code> while online to enable diagrams." +
                      "</span><br><br>" + escapeHtml(n.dataset.src || "");
      });
      return;
    }
    nodes.forEach(function (n) {
      n.removeAttribute("data-processed");
      n.textContent = n.dataset.src || n.textContent;
    });
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: MERMAID_THEME[styleName] || "default",
        fontFamily: getComputedStyle(document.body).fontFamily,
        maxTextSize: 500000,
        flowchart: { useMaxWidth: false },
        sequence: { useMaxWidth: false },
        gantt: ganttConfig(styleName, nodes)
      });
      window.mermaid.run({ nodes: nodes, suppressErrors: true });
    } catch (err) {
      console.error("mermaid", err);
    }
  }

  /* Gantt layout. Mermaid's defaults everywhere except github-ext, which
     also gets larger type and a left gutter wide enough for the longest
     section title (mermaid never wraps those, so they ran into the bars).
     Every value is given explicitly so switching back restores the defaults. */
  var GANTT_RE = /(^|\n)\s*gantt\b/;
  function ganttConfig(styleName, nodes) {
    if (styleName !== "github-ext") {
      return { useMaxWidth: false, fontSize: 11, sectionFontSize: 11,
               barHeight: 20, leftPadding: 75 };
    }
    var longest = 0;
    Array.prototype.forEach.call(nodes, function (n) {
      (n.dataset.src || "").split("\n").forEach(function (line) {
        var m = /^\s*section\s+(.+?)\s*$/i.exec(line);
        if (m && m[1].length > longest) longest = m[1].length;
      });
    });
    // The window's width at 100%, whatever the zoom: zooming in then makes
    // the chart wider than the window, so there is something to pan across,
    // instead of redrawing it to fit at a larger type size.
    var gutter = mode === "mermaid" ? 48 : 80;     // #content side padding
    return { useMaxWidth: false, fontSize: 13, sectionFontSize: 13, barHeight: 22,
             useWidth: Math.max(400, scroller.clientWidth - gutter),
             leftPadding: Math.max(75, Math.min(320, Math.round(longest * 7.5) + 24)) };
  }

  /* A gantt chart is drawn at a fixed width, once. In github-ext that width is
     the window's, so redraw when the window or the sidebar changes it. The
     scroller is watched rather than the content: zooming must not redraw. */
  if (window.ResizeObserver && scroller) {
    var ganttWidth = 0, ganttTimer = null;
    new ResizeObserver(function () {
      var w = scroller.clientWidth;
      if (!ganttWidth) { ganttWidth = w; return; }
      if (Math.abs(w - ganttWidth) < 2) return;
      ganttWidth = w;
      if (currentStyle() !== "github-ext" || typeof window.mermaid === "undefined") return;
      var hasGantt = Array.prototype.some.call(
        document.querySelectorAll("pre.mermaid"),
        function (n) { return GANTT_RE.test(n.dataset.src || ""); });
      if (!hasGantt) return;
      clearTimeout(ganttTimer);
      ganttTimer = setTimeout(function () { renderMermaid(currentStyle()); }, 200);
    }).observe(scroller);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }

  window.__mdv_mermaidReady = function () {
    renderMermaid(currentStyle());
  };

  /* ------------------------------------------------------------------ */
  /* python bridge helpers                                              */
  /* ------------------------------------------------------------------ */

  function call(name) {
    callAsync.apply(null, arguments).catch(function () {
      // The bridge may be loading, or the call may have replaced this page.
    });
  }

  /* report scroll position so a reload can restore it */
  window.__mdv_scroll = function () {
    var max = scroller.scrollHeight - scroller.clientHeight;
    return max > 0 ? scroller.scrollTop / max : 0;
  };

  /* ------------------------------------------------------------------ */
  /* wire up the toolbar                                                */
  /* ------------------------------------------------------------------ */

  function on(id, fn, inContent) {
    // getElementById returns the first match: a document could plant an id the toolbar lacks in this mode.
    var el = document.getElementById(id);
    if (el && (inContent || !el.closest("#content"))) el.addEventListener("click", fn);
  }
  on("zoomIn", function () { step(+1); });
  on("zoomOut", function () { step(-1); });
  on("fitBtn", doFit);
  on("backBtn", function () { call("go_back"); });
  on("openBtn", function () { call("pick_file"); });
  // The welcome and error pages (mode "blank") are md-view's own markup; elsewhere #content is the document.
  if (mode === "blank") on("pickFile", function () { call("pick_file"); }, true);
  on("reloadBtn", function () { call("refresh"); });
  if (label) label.addEventListener("click", function () { setZoom(1); });

  /* ------------------------------------------------------------------ */
  /* boot                                                               */
  /* ------------------------------------------------------------------ */

  applyStyle(currentStyle(), { silent: true });
  applyFont(currentFont(), { silent: true });
  render();
  if (CFG.scroll && mode !== "image") {
    requestAnimationFrame(function () {
      var max = scroller.scrollHeight - scroller.clientHeight;
      if (max > 0) scroller.scrollTop = CFG.scroll * max;
    });
  }
})();
"""
