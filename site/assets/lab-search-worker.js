/**
 * Schema Lab search off the main thread.
 *   { type: 'reset' }
 *   { type: 'add', rows, done? }
 *   { type: 'query', id, filters, page, pageSize }
 */
const DENY = new Set(["command", "shell", "raw", "script"]);

/** @type {object[]} */
let all = [];

function scoreItem(item, q) {
  const fqcn = String(item.fqcn || "").toLowerCase();
  const short = String(item.shortName || "").toLowerCase();
  const col = String(item.collection || "").toLowerCase();
  const desc = String(item.description || "").toLowerCase();
  const hay = fqcn + " " + short + " " + col + " " + desc;
  if (!hay.includes(q)) return -1;
  let score = 10;
  if (fqcn === q || short === q) score += 100;
  else if (fqcn.endsWith("." + q) || short.startsWith(q)) score += 50;
  else if (fqcn.includes(q)) score += 25;
  else if (col.includes(q)) score += 15;
  return score;
}

function filterAndPage(filters, page, pageSize) {
  const q = String(filters.q || "")
    .trim()
    .toLowerCase();
  const collection = String(filters.collection || "").trim().toLowerCase();
  const shortMod = q.includes(".") ? q.split(".").pop() : q;

  if (q && (DENY.has(shortMod) || DENY.has(q))) {
    return {
      total: 1,
      totalPages: 1,
      page: 1,
      rows: [
        {
          _deny: true,
          fqcn: filters.q || q,
          shortName: shortMod,
          collection: "",
          description: "Free-form module — denied by default",
        },
      ],
    };
  }

  let scored;
  if (!q && !collection) {
    scored = all.map((item) => [0, item]);
  } else {
    scored = [];
    for (let i = 0; i < all.length; i++) {
      const item = all[i];
      if (collection) {
        const col = String(item.collection || "").toLowerCase();
        if (col !== collection && !col.startsWith(collection + ".")) continue;
      }
      if (!q) {
        scored.push([0, item]);
        continue;
      }
      const s = scoreItem(item, q);
      if (s < 0) continue;
      scored.push([s, item]);
    }
    if (q) {
      scored.sort(
        (a, b) =>
          b[0] - a[0] ||
          String(a[1].fqcn).localeCompare(String(b[1].fqcn)),
      );
    }
  }

  const total = scored.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1);
  let p = Math.max(1, page | 0);
  if (p > totalPages) p = totalPages;
  const start = (p - 1) * pageSize;
  const rows = scored.slice(start, start + pageSize).map((x) => x[1]);
  return { total, totalPages, page: p, rows };
}

self.onmessage = (ev) => {
  const msg = ev.data || {};
  if (msg.type === "reset") {
    all = [];
    self.postMessage({ type: "progress", total: 0, loaded: true });
    return;
  }
  if (msg.type === "add" && Array.isArray(msg.rows)) {
    for (let i = 0; i < msg.rows.length; i++) all.push(msg.rows[i]);
    self.postMessage({
      type: "progress",
      total: all.length,
      loaded: Boolean(msg.done),
    });
    return;
  }
  if (msg.type === "query") {
    const pageSize = Math.max(1, Number(msg.pageSize) || 48);
    const page = Math.max(1, Number(msg.page) || 1);
    const result = filterAndPage(msg.filters || {}, page, pageSize);
    self.postMessage({
      type: "result",
      id: msg.id,
      corpus: all.length,
      loaded: Boolean(msg.loaded),
      pageSize,
      ...result,
    });
  }
};
