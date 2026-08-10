(function () {
  const DENY = new Set(["command", "shell", "raw", "script"]);
  const statusEl = document.getElementById("lab-status");
  const inputEl = document.getElementById("lab-q");
  const resultsEl = document.getElementById("lab-results");
  const metaEl = document.getElementById("lab-meta");
  const schemaHead = document.getElementById("lab-schema-head");
  const schemaBody = document.getElementById("lab-schema-body");
  const previewEl = document.getElementById("lab-preview");
  const checkEl = document.getElementById("lab-check");

  if (!inputEl || !resultsEl) return;

  let gallery = [];
  let selected = null;
  let schemaRoot = null;

  function setStatus(msg, cls) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.className = "lab-status" + (cls ? " " + cls : "");
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

  async function loadGallery() {
    const cached = sessionStorage.getItem("af-gallery-v1");
    if (cached) {
      try {
        gallery = JSON.parse(cached);
        if (Array.isArray(gallery) && gallery.length) {
          schemaRoot = sessionStorage.getItem("af-schema-root") || "catalog";
          setStatus("Gallery ready · " + gallery.length.toLocaleString() + " modules (cached)", "ok");
          renderResults(searchModules("", 40));
          return;
        }
      } catch (_) {
        /* fall through */
      }
    }

    setStatus("Loading gallery…");
    let lastErr = null;
    for (const root of catalogCandidates()) {
      try {
        const res = await fetch(root + "/gallery.json", { cache: "force-cache" });
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        if (!Array.isArray(data)) throw new Error("bad gallery shape");
        gallery = data.filter((x) => x && x.fqcn);
        schemaRoot = root;
        try {
          sessionStorage.setItem("af-gallery-v1", JSON.stringify(gallery));
          sessionStorage.setItem("af-schema-root", root);
        } catch (_) {
          /* quota */
        }
        setStatus("Gallery ready · " + gallery.length.toLocaleString() + " modules", "ok");
        renderResults(searchModules("", 40));
        return;
      } catch (e) {
        lastErr = e;
      }
    }
    setStatus(
      "Could not load gallery.json. Serve site with catalog/ (see site/README.md). " +
        (lastErr ? String(lastErr.message || lastErr) : ""),
      "err"
    );
    resultsEl.innerHTML =
      '<li class="schema-empty">No gallery loaded. Run <span class="mono">./scripts/site_preview.sh</span> or open the GitHub Pages deploy.</li>';
  }

  function searchModules(query, limit) {
    const q = (query || "").trim().toLowerCase();
    const lim = Math.max(1, Math.min(limit || 40, 100));
    if (!q) return gallery.slice(0, lim);

    const shortMod = q.includes(".") ? q.split(".").pop() : q;
    if (DENY.has(shortMod) || DENY.has(q)) {
      return [{ _deny: true, fqcn: q, shortName: shortMod, description: "Free-form module — denied by default" }];
    }

    const scored = [];
    for (const item of gallery) {
      const fqcn = String(item.fqcn || "").toLowerCase();
      const short = String(item.shortName || "").toLowerCase();
      const col = String(item.collection || "").toLowerCase();
      const desc = String(item.description || "").toLowerCase();
      const hay = fqcn + " " + short + " " + col + " " + desc;
      if (!hay.includes(q)) continue;
      let score = 10;
      if (fqcn === q || short === q) score += 100;
      else if (fqcn.endsWith("." + q) || short.startsWith(q)) score += 50;
      else if (fqcn.includes(q)) score += 25;
      scored.push([score, item]);
    }
    scored.sort((a, b) => b[0] - a[0] || String(a[1].fqcn).localeCompare(String(b[1].fqcn)));
    return scored.slice(0, lim).map((x) => x[1]);
  }

  function renderResults(items) {
    resultsEl.innerHTML = "";
    if (metaEl) {
      metaEl.textContent = items.length
        ? items[0]._deny
          ? "Policy hit"
          : items.length + " shown"
        : "No matches";
    }
    if (!items.length) {
      resultsEl.innerHTML = '<li class="schema-empty">No modules match.</li>';
      return;
    }
    const frag = document.createDocumentFragment();
    for (const item of items) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("aria-selected", selected && selected.fqcn === item.fqcn ? "true" : "false");
      if (item._deny) {
        btn.innerHTML =
          '<span class="r-fqcn" style="color:var(--deny)">' +
          esc(item.fqcn) +
          '</span><span class="r-desc">' +
          esc(item.description) +
          "</span>";
        btn.addEventListener("click", () => showDeny(item));
      } else {
        btn.innerHTML =
          '<span class="r-fqcn">' +
          esc(item.fqcn) +
          '</span><span class="r-desc">' +
          esc(item.description || "") +
          '</span><div class="r-col">' +
          esc(item.collection || "") +
          "</div>";
        btn.addEventListener("click", () => selectModule(item, btn));
      }
      li.appendChild(btn);
      frag.appendChild(li);
    }
    resultsEl.appendChild(frag);
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showDeny(item) {
    selected = item;
    resultsEl.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", "false"));
    if (schemaHead) {
      schemaHead.innerHTML =
        "<h3 style=\"color:var(--deny)\">" +
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
    resultsEl.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", "false"));
    if (btn) btn.setAttribute("aria-selected", "true");

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
          "<h3>" + esc(item.fqcn) + "</h3><p>" + esc(item.description || "") + "</p>";
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
        ? ' · <a href="' + esc(schema.docUrl) + '" target="_blank" rel="noopener">docs</a>'
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
      schemaBody.innerHTML = '<div class="schema-empty">Schema has no options list.</div>';
      return;
    }
    const frag = document.createDocumentFragment();
    for (const opt of opts) {
      const row = document.createElement("div");
      row.className = "opt-row";
      const left = document.createElement("div");
      left.innerHTML =
        '<div class="opt-name">' +
        esc(opt.name || "?") +
        (opt.required ? '<span class="req">*</span>' : "") +
        '</div><div class="opt-badges">' +
        '<span class="badge type">' +
        esc(opt.type || "any") +
        "</span>" +
        (opt.noLog ? '<span class="badge nolog">no_log</span>' : "") +
        "</div>";
      const right = document.createElement("div");
      let html = '<div class="opt-desc">' + esc(opt.description || "") + "</div>";
      if (opt.default !== undefined && opt.default !== null) {
        html +=
          '<div class="opt-default">default: ' +
          esc(typeof opt.default === "object" ? JSON.stringify(opt.default) : String(opt.default)) +
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

  let t = null;
  inputEl.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => {
      renderResults(searchModules(inputEl.value, 50));
    }, 120);
  });

  if (checkEl) {
    checkEl.addEventListener("change", () => {
      if (selected && selected._deny) updatePreview(null, true);
      else updatePreview(selected ? { fqcn: selected.fqcn } : null, false);
    });
  }

  loadGallery();
})();
