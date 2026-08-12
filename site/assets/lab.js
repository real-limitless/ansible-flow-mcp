(function () {
  const DENY = new Set(["command", "shell", "raw", "script"]);
  const statusEl = document.getElementById("lab-status");
  const loadBar = document.getElementById("lab-load");
  const inputEl = document.getElementById("lab-q");
  const resultsEl = document.getElementById("lab-results");
  const cardGrid = document.getElementById("lab-cards");
  const metaEl = document.getElementById("lab-meta");
  const schemaHead = document.getElementById("lab-schema-head");
  const schemaBody = document.getElementById("lab-schema-body");
  const previewEl = document.getElementById("lab-preview");
  const checkEl = document.getElementById("lab-check");
  const collectionEl = document.getElementById("lab-collection");
  const pageSizeEl = document.getElementById("lab-page-size");
  const resultsBody = document.getElementById("lab-results-body");

  if (!inputEl || (!resultsEl && !cardGrid)) return;

  let selected = null;
  let schemaRoot = null;
  let collections = [];
  const state = {
    page: 1,
    queryId: 0,
    loaded: false,
    corpus: 0,
    debounce: null,
    view: "list",
  };

  const PAGE_SIZES = [24, 48, 96];
  const DEFAULT_PAGE_SIZE = 48;

  function setStatus(msg, cls) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.className = "lab-status" + (cls ? " " + cls : "");
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function catalogCandidates() {
    const base = document.documentElement.getAttribute("data-base") || "";
    const roots = [
      base.replace(/\/?$/, "/") + "catalog",
      "catalog",
      "../catalog",
      "./catalog",
    ];
    return [...new Set(roots.map((r) => r.replace(/\/+$/, "")))];
  }

  function workerUrl() {
    const scripts = document.getElementsByTagName("script");
    let base = "assets/";
    for (let i = 0; i < scripts.length; i++) {
      const src = scripts[i].src || "";
      if (src.indexOf("lab.js") !== -1) {
        base = src.replace(/lab\.js(\?.*)?$/, "");
        break;
      }
    }
    return base + "lab-search-worker.js";
  }

  const worker = new Worker(workerUrl());

  worker.onmessage = function (ev) {
    const msg = ev.data || {};
    if (msg.type === "progress") {
      state.corpus = msg.total;
      state.loaded = Boolean(msg.loaded);
      if (loadBar) {
        loadBar.hidden = state.loaded;
        loadBar.textContent = state.loaded
          ? ""
          : "Loading gallery index… " + msg.total.toLocaleString() + " modules";
      }
      scheduleQuery(false);
      return;
    }
    if (msg.type === "result") {
      if (msg.id !== state.queryId) return;
      applyResult(msg);
    }
  };

  worker.onerror = function () {
    setStatus("Search worker failed", "err");
  };

  function readFilters() {
    const ps = Number(pageSizeEl && pageSizeEl.value) || DEFAULT_PAGE_SIZE;
    return {
      q: (inputEl.value || "").trim(),
      collection: (collectionEl && collectionEl.value) || "",
      pageSize: PAGE_SIZES.indexOf(ps) >= 0 ? ps : DEFAULT_PAGE_SIZE,
      view: state.view,
    };
  }

  function applyUrl() {
    const sp = new URLSearchParams(location.search);
    if (sp.has("q")) inputEl.value = sp.get("q") || "";
    if (collectionEl && sp.get("collection"))
      collectionEl.value = sp.get("collection");
    const ps = Number(sp.get("pageSize") || DEFAULT_PAGE_SIZE);
    if (pageSizeEl && PAGE_SIZES.indexOf(ps) >= 0)
      pageSizeEl.value = String(ps);
    state.page = Math.max(1, Number(sp.get("page") || 1) || 1);
    setView(sp.get("view") === "cards" ? "cards" : "list");
  }

  function writeUrl(f, page) {
    const sp = new URLSearchParams();
    if (f.q) sp.set("q", f.q);
    if (f.collection) sp.set("collection", f.collection);
    if (f.pageSize !== DEFAULT_PAGE_SIZE) sp.set("pageSize", String(f.pageSize));
    if (f.view === "cards") sp.set("view", "cards");
    if (page > 1) sp.set("page", String(page));
    const qs = sp.toString();
    history.replaceState(
      null,
      "",
      location.pathname + (qs ? "?" + qs : "") + (location.hash || ""),
    );
  }

  function setView(view) {
    state.view = view === "cards" ? "cards" : "list";
    const listWrap = document.getElementById("lab-list-wrap");
    const cardsWrap = document.getElementById("lab-cards-wrap");
    const btnList = document.getElementById("lab-view-list");
    const btnCards = document.getElementById("lab-view-cards");
    if (listWrap) listWrap.hidden = state.view !== "list";
    if (cardsWrap) cardsWrap.hidden = state.view !== "cards";
    if (btnList) btnList.classList.toggle("on", state.view === "list");
    if (btnCards) btnCards.classList.toggle("on", state.view === "cards");
    if (resultsBody) resultsBody.setAttribute("data-view", state.view);
  }

  function updatePager(page, totalPages, total) {
    ["lab-pager-top", "lab-pager"].forEach(function (id) {
      const root = document.getElementById(id);
      if (!root) return;
      root.hidden = total === 0;
      const info = root.querySelector(".pager-info");
      const prev = root.querySelector(".page-prev");
      const next = root.querySelector(".page-next");
      const jump = root.querySelector(".page-jump-input");
      if (info) {
        info.textContent =
          totalPages <= 1
            ? total + " result" + (total === 1 ? "" : "s")
            : "Page " + page + " / " + totalPages;
      }
      if (prev) prev.disabled = page <= 1 || totalPages <= 1;
      if (next) next.disabled = page >= totalPages || totalPages <= 1;
      if (jump) {
        jump.max = String(Math.max(1, totalPages));
        jump.value = String(page);
        jump.disabled = totalPages <= 1;
      }
    });
  }

  function applyResult(msg) {
    const f = readFilters();
    state.page = msg.page;
    writeUrl(f, msg.page);
    setSkeleton(false);

    if (metaEl) {
      const start = msg.total === 0 ? 0 : (msg.page - 1) * msg.pageSize + 1;
      const end = Math.min(msg.page * msg.pageSize, msg.total);
      const range =
        msg.total === 0 ? "0 results" : start + "–" + end + " of " + msg.total;
      const bits = [range];
      if (!msg.loaded && msg.corpus)
        bits.push("index " + msg.corpus.toLocaleString());
      metaEl.textContent = bits.join(" · ");
    }

    if (!msg.total) {
      if (resultsEl) resultsEl.innerHTML = "";
      if (cardGrid) cardGrid.innerHTML = "";
      const empty = document.getElementById("lab-empty");
      if (empty) {
        empty.hidden = false;
        empty.textContent = "No modules match.";
      }
      updatePager(1, 1, 0);
      return;
    }
    const empty = document.getElementById("lab-empty");
    if (empty) empty.hidden = true;

    if (f.view === "cards") {
      if (resultsEl) resultsEl.innerHTML = "";
      if (cardGrid) {
        cardGrid.innerHTML = msg.rows
          .map(function (item) {
            if (item._deny) {
              return (
                '<button type="button" class="lab-card deny" data-deny="1" data-fqcn="' +
                esc(item.fqcn) +
                '"><span class="r-fqcn">' +
                esc(item.fqcn) +
                '</span><span class="r-desc">' +
                esc(item.description || "") +
                "</span></button>"
              );
            }
            return (
              '<button type="button" class="lab-card" data-fqcn="' +
              esc(item.fqcn) +
              '"><span class="r-fqcn">' +
              esc(item.fqcn) +
              '</span><span class="r-desc">' +
              esc(item.description || "") +
              '</span><span class="r-col">' +
              esc(item.collection || "") +
              "</span></button>"
            );
          })
          .join("");
        bindResultClicks(cardGrid, msg.rows);
      }
    } else {
      if (cardGrid) cardGrid.innerHTML = "";
      if (resultsEl) {
        resultsEl.innerHTML = msg.rows
          .map(function (item) {
            if (item._deny) {
              return (
                '<li><button type="button" data-deny="1" data-fqcn="' +
                esc(item.fqcn) +
                '"><span class="r-fqcn" style="color:var(--deny)">' +
                esc(item.fqcn) +
                '</span><span class="r-desc">' +
                esc(item.description || "") +
                "</span></button></li>"
              );
            }
            const sel =
              selected && selected.fqcn === item.fqcn ? ' aria-selected="true"' : "";
            return (
              "<li><button type=\"button\" data-fqcn=\"" +
              esc(item.fqcn) +
              '"' +
              sel +
              '><span class="r-fqcn">' +
              esc(item.fqcn) +
              '</span><span class="r-desc">' +
              esc(item.description || "") +
              '</span><div class="r-col">' +
              esc(item.collection || "") +
              "</div></button></li>"
            );
          })
          .join("");
        bindResultClicks(resultsEl, msg.rows);
      }
    }
    updatePager(msg.page, msg.totalPages, msg.total);
  }

  function bindResultClicks(root, rows) {
    const byFqcn = {};
    rows.forEach(function (r) {
      byFqcn[r.fqcn] = r;
    });
    root.querySelectorAll("button[data-fqcn]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const fqcn = btn.getAttribute("data-fqcn");
        const item = byFqcn[fqcn];
        if (!item) return;
        if (item._deny || btn.getAttribute("data-deny") === "1") showDeny(item);
        else selectModule(item, btn);
      });
    });
  }

  function runQuery(resetPage) {
    if (resetPage) state.page = 1;
    const f = readFilters();
    state.queryId += 1;
    worker.postMessage({
      type: "query",
      id: state.queryId,
      filters: { q: f.q, collection: f.collection },
      page: state.page,
      pageSize: f.pageSize,
      loaded: state.loaded,
    });
  }

  function scheduleQuery(immediate) {
    if (immediate) {
      if (state.debounce) clearTimeout(state.debounce);
      runQuery(true);
      return;
    }
    if (state.debounce) clearTimeout(state.debounce);
    state.debounce = setTimeout(function () {
      runQuery(true);
    }, 220);
  }

  function setSkeleton(on) {
    const sk = document.getElementById("lab-skeleton");
    if (sk) sk.hidden = !on;
  }

  function fillCollections(list) {
    if (!collectionEl || !list || !list.length) return;
    const cur = collectionEl.value;
    const opts = ['<option value="">Any collection</option>'];
    list.forEach(function (c) {
      opts.push(
        '<option value="' +
          esc(c.name) +
          '">' +
          esc(c.name) +
          " (" +
          c.count +
          ")</option>",
      );
    });
    collectionEl.innerHTML = opts.join("");
    if (cur) collectionEl.value = cur;
  }

  async function loadBrowse() {
    worker.postMessage({ type: "reset" });
    setSkeleton(true);
    setStatus("Loading gallery index…");
    const roots = catalogCandidates();
    let manifest = null;
    let rootUsed = null;

    for (let i = 0; i < roots.length; i++) {
      const root = roots[i];
      try {
        const res = await fetch(root + "/browse/manifest.json", {
          cache: "no-cache",
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        manifest = await res.json();
        rootUsed = root;
        break;
      } catch (_) {
        /* try next */
      }
    }

    if (!manifest || !rootUsed) {
      await loadGalleryFallback(roots);
      return;
    }

    schemaRoot = rootUsed;
    collections = manifest.collections || [];
    fillCollections(collections);
    setStatus(
      (manifest.total || 0).toLocaleString() +
        " modules · loading shards…",
    );
    if (loadBar) {
      loadBar.hidden = false;
      loadBar.textContent =
        "Loading gallery index… 0/" + (manifest.shardCount || 0) + " shards";
    }

    const shards = manifest.shards || [];
    for (let i = 0; i < shards.length; i++) {
      const res = await fetch(rootUsed + "/browse/" + shards[i]);
      if (!res.ok) continue;
      const rows = await res.json();
      const done = i === shards.length - 1;
      worker.postMessage({ type: "add", rows: rows, done: done });
      if (loadBar) {
        loadBar.textContent = done
          ? ""
          : "Loading gallery index… " +
            (i + 1) +
            "/" +
            shards.length +
            " shards";
        if (done) loadBar.hidden = true;
      }
      if (i === 0) runQuery(true);
      await new Promise(function (r) {
        setTimeout(r, 0);
      });
    }
    state.loaded = true;
    setStatus(
      (manifest.total || 0).toLocaleString() + " modules · browse ready",
      "ok",
    );
    runQuery(false);
  }

  async function loadGalleryFallback(roots) {
    setStatus("Browse shards missing — loading gallery.json…");
    for (let i = 0; i < roots.length; i++) {
      const root = roots[i];
      try {
        const res = await fetch(root + "/gallery.json");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        if (!Array.isArray(data)) throw new Error("bad gallery");
        const rows = data
          .filter(function (x) {
            return x && x.fqcn;
          })
          .map(function (x) {
            return {
              fqcn: x.fqcn,
              shortName: x.shortName || String(x.fqcn).split(".").pop(),
              collection: x.collection || "",
              description: String(x.description || "").slice(0, 120),
            };
          });
        schemaRoot = root;
        const colCount = {};
        rows.forEach(function (r) {
          if (r.collection)
            colCount[r.collection] = (colCount[r.collection] || 0) + 1;
        });
        collections = Object.keys(colCount)
          .map(function (name) {
            return { name: name, count: colCount[name] };
          })
          .sort(function (a, b) {
            return b.count - a.count;
          })
          .slice(0, 80);
        fillCollections(collections);
        worker.postMessage({ type: "add", rows: rows, done: true });
        state.loaded = true;
        setSkeleton(false);
        setStatus(rows.length.toLocaleString() + " modules (legacy gallery)", "ok");
        runQuery(true);
        return;
      } catch (_) {
        /* next */
      }
    }
    setSkeleton(false);
    setStatus(
      "Could not load browse/ or gallery.json. Run scripts/generate_browse.py and site_preview.sh",
      "err",
    );
    const empty = document.getElementById("lab-empty");
    if (empty) {
      empty.hidden = false;
      empty.innerHTML =
        'No gallery loaded. Run <span class="mono">python3 scripts/generate_browse.py && ./scripts/site_preview.sh</span>';
    }
  }

  function showDeny(item) {
    selected = item;
    if (schemaHead) {
      schemaHead.innerHTML =
        '<h3 style="color:var(--deny)">' +
        esc(item.fqcn) +
        "</h3><p>Free-form execution module — refused by policy.</p>";
    }
    if (schemaBody) {
      schemaBody.innerHTML =
        '<div class="schema-empty deny">command / shell / raw / script are denied by default. Agents get structured modules from the gallery — not a root shell.</div>';
    }
    updatePreview(null, true);
  }

  async function selectModule(item, btn) {
    selected = item;
    document
      .querySelectorAll("#lab-results button, #lab-cards button")
      .forEach(function (b) {
        b.setAttribute(
          "aria-selected",
          b.getAttribute("data-fqcn") === item.fqcn ? "true" : "false",
        );
      });

    const short = String(item.shortName || item.fqcn.split(".").pop()).toLowerCase();
    if (DENY.has(short)) {
      showDeny(item);
      return;
    }

    if (schemaHead) {
      schemaHead.innerHTML =
        "<h3>" + esc(item.fqcn) + "</h3><p>Loading slim argSpec…</p>";
    }
    if (schemaBody) {
      schemaBody.innerHTML = '<div class="schema-empty">Fetching schema…</div>';
    }

    const root = schemaRoot || "catalog";
    const url = root + "/schemas/" + item.fqcn + ".json";
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const schema = await res.json();
      renderSchema(schema);
      updatePreview(schema, false);
    } catch (e) {
      if (schemaHead) {
        schemaHead.innerHTML =
          "<h3>" +
          esc(item.fqcn) +
          "</h3><p>" +
          esc(item.description || "") +
          "</p>";
      }
      if (schemaBody) {
        schemaBody.innerHTML =
          '<div class="schema-empty">No committed schema JSON for this FQCN under catalog/schemas/.<br/><span class="mono">' +
          esc(String(e.message || e)) +
          "</span></div>";
      }
      updatePreview(null, false);
    }
  }

  function renderSchema(schema) {
    if (schemaHead) {
      const doc = schema.docUrl
        ? ' · <a href="' +
          esc(schema.docUrl) +
          '" target="_blank" rel="noopener">docs</a>'
        : "";
      schemaHead.innerHTML =
        "<h3>" +
        esc(schema.fqcn || selected.fqcn) +
        "</h3><p>" +
        esc(schema.shortDescription || selected.description || "") +
        doc +
        "</p>";
    }
    const opts = Array.isArray(schema.options) ? schema.options : [];
    if (!opts.length) {
      schemaBody.innerHTML =
        '<div class="schema-empty">Schema has no options list.</div>';
      return;
    }
    const frag = document.createDocumentFragment();
    for (let i = 0; i < opts.length; i++) {
      const opt = opts[i];
      const row = document.createElement("div");
      row.className = "opt-row";
      const left = document.createElement("div");
      left.innerHTML =
        '<div class="opt-name">' +
        esc(opt.name || "?") +
        (opt.required ? '<span class="req">*</span>' : "") +
        '</div><div class="opt-badges"><span class="badge type">' +
        esc(opt.type || "any") +
        "</span>" +
        (opt.noLog ? '<span class="badge nolog">no_log</span>' : "") +
        "</div>";
      const right = document.createElement("div");
      let html =
        '<div class="opt-desc">' + esc(opt.description || "") + "</div>";
      if (opt.default !== undefined && opt.default !== null) {
        html +=
          '<div class="opt-default">default: ' +
          esc(
            typeof opt.default === "object"
              ? JSON.stringify(opt.default)
              : String(opt.default),
          ) +
          "</div>";
      }
      if (Array.isArray(opt.choices) && opt.choices.length) {
        html +=
          '<div class="opt-choices">choices: ' +
          esc(opt.choices.map(String).join(" · ")) +
          "</div>";
      }
      right.innerHTML = html;
      row.appendChild(left);
      row.appendChild(right);
      frag.appendChild(row);
    }
    schemaBody.innerHTML = "";
    schemaBody.appendChild(frag);
  }

  function updatePreview(schema, denied) {
    if (!previewEl) return;
    const check = checkEl ? checkEl.checked : true;
    if (denied) {
      previewEl.className = "lab-preview bad";
      previewEl.textContent = "run_module → DENIED (free-form module)";
      return;
    }
    if (!schema && !selected) {
      previewEl.className = "lab-preview";
      previewEl.textContent = "Select a module to preview the agent ritual";
      return;
    }
    const fqcn = (schema && schema.fqcn) || (selected && selected.fqcn) || "…";
    previewEl.className = "lab-preview ok";
    previewEl.textContent =
      "get_module_schema → run_module(" +
      fqcn +
      ", check_mode=" +
      check +
      ")" +
      (check ? "  // dry-run default" : "  // apply");
  }

  function bindPager(id) {
    const root = document.getElementById(id);
    if (!root) return;
    root.querySelector(".page-prev") &&
      root.querySelector(".page-prev").addEventListener("click", function () {
        state.page = Math.max(1, state.page - 1);
        runQuery(false);
        document.getElementById("schema-lab") &&
          document.getElementById("schema-lab").scrollIntoView({
            block: "nearest",
            behavior: "smooth",
          });
      });
    root.querySelector(".page-next") &&
      root.querySelector(".page-next").addEventListener("click", function () {
        state.page += 1;
        runQuery(false);
      });
    root.querySelector(".page-go") &&
      root.querySelector(".page-go").addEventListener("click", function () {
        const jump = Number(
          (root.querySelector(".page-jump-input") || {}).value || 1,
        );
        state.page = Math.max(1, jump || 1);
        runQuery(false);
      });
  }

  applyUrl();
  bindPager("lab-pager-top");
  bindPager("lab-pager");

  inputEl.addEventListener("input", function () {
    scheduleQuery(false);
  });
  if (collectionEl)
    collectionEl.addEventListener("change", function () {
      runQuery(true);
    });
  if (pageSizeEl)
    pageSizeEl.addEventListener("change", function () {
      runQuery(true);
    });

  document.getElementById("lab-view-list") &&
    document.getElementById("lab-view-list").addEventListener("click", function () {
      setView("list");
      runQuery(false);
    });
  document.getElementById("lab-view-cards") &&
    document
      .getElementById("lab-view-cards")
      .addEventListener("click", function () {
        setView("cards");
        runQuery(false);
      });

  document.getElementById("lab-reset") &&
    document.getElementById("lab-reset").addEventListener("click", function () {
      inputEl.value = "";
      if (collectionEl) collectionEl.value = "";
      if (pageSizeEl) pageSizeEl.value = String(DEFAULT_PAGE_SIZE);
      setView("list");
      state.page = 1;
      runQuery(true);
    });

  if (checkEl) {
    checkEl.addEventListener("change", function () {
      if (selected && selected._deny) updatePreview(null, true);
      else updatePreview(selected ? { fqcn: selected.fqcn } : null, false);
    });
  }

  loadBrowse();
})();
