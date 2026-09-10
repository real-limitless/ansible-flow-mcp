const $ = (s) => document.querySelector(s);
let csrf = "";

function showErr(msg) {
  const el = $("#err");
  el.hidden = !msg;
  el.textContent = msg || "";
}

async function api(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (csrf && method !== "GET" && method !== "HEAD") headers["X-CSRF-Token"] = csrf;
  const res = await fetch(path, { ...opts, headers });
  const body = await res.json().catch(() => ({}));
  if (res.status === 401) {
    location.replace("/login");
    throw new Error("unauthorized");
  }
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function renderServers() {
  const st = await api("/api/status");
  const nodes = st.nodes || [];
  const rows = nodes
    .map(
      (n) => `
      <tr>
        <td class="mono">${esc(n.name)}</td>
        <td>${esc(n.kind || "spoke")}</td>
        <td class="mono">${esc(n.ansible_host || "")}</td>
        <td>${esc(n.ansible_port || "")}</td>
        <td>${esc(n.ansible_user || "")}</td>
        <td class="row-actions">
          ${
            n.kind === "target"
              ? ""
              : `<button class="pill-btn" data-ping="${esc(n.name)}">Ping</button>`
          }
          <button class="pill-btn danger" data-revoke="${esc(n.name)}">Revoke</button>
        </td>
      </tr>`,
    )
    .join("");
  $("#tab-servers").innerHTML = `
    <div class="surface">
      <div class="panel-head">Invite spoke</div>
      <div class="panel-pad">
        <form id="invite" class="row-actions">
          <input name="name" placeholder="spoke name" required />
          <input name="public_addr" placeholder="public-addr (optional)" />
          <input name="ttl" value="15m" style="width:6rem" />
          <button class="pill-btn primary" type="submit">Invite</button>
        </form>
        <div id="inviteOut"></div>
      </div>
    </div>
    <div class="surface">
      <div class="panel-head">Servers</div>
      <div class="panel-pad">
        <table>
          <thead><tr><th>Name</th><th>Kind</th><th>Host</th><th>Port</th><th>User</th><th></th></tr></thead>
          <tbody>${rows || `<tr><td colspan="6" class="muted">No enrolled nodes</td></tr>`}</tbody>
        </table>
      </div>
    </div>`;
  $("#invite").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const issued = await api("/api/invite", {
        method: "POST",
        body: JSON.stringify({
          name: fd.get("name"),
          public_addr: fd.get("public_addr"),
          ttl: fd.get("ttl"),
        }),
      });
      $("#inviteOut").innerHTML = `<p class="muted">Token shown once. Run on the spoke:</p><pre>${esc(issued.join_command)}</pre>`;
    } catch (err) {
      showErr(err.message);
    }
  });
  document.querySelectorAll("[data-ping]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const r = await api(`/api/nodes/${encodeURIComponent(btn.dataset.ping)}/ping`, {
          method: "POST",
        });
        showErr(r.ok ? "" : r.error || "ping failed");
        if (r.ok) btn.textContent = "ok";
      } catch (err) {
        showErr(err.message);
      }
    });
  });
  document.querySelectorAll("[data-revoke]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`Revoke ${btn.dataset.revoke}?`)) return;
      try {
        await api(`/api/nodes/${encodeURIComponent(btn.dataset.revoke)}`, { method: "DELETE" });
        await renderServers();
      } catch (err) {
        showErr(err.message);
      }
    });
  });
}

async function renderGroups() {
  const st = await api("/api/groups");
  const groups = st.groups || [];
  const rows = groups
    .map((g) => {
      const name = g.name || g;
      const hosts = Array.isArray(g.hosts) ? g.hosts.join(", ") : "";
      return `<tr>
        <td class="mono">${esc(name)}</td>
        <td>${esc(hosts)}</td>
        <td class="row-actions">
          <button class="pill-btn" data-members="${esc(name)}">Set members</button>
          <button class="pill-btn danger" data-del="${esc(name)}">Delete</button>
        </td>
      </tr>`;
    })
    .join("");
  $("#tab-groups").innerHTML = `
    <div class="surface">
      <div class="panel-head">Create group</div>
      <div class="panel-pad">
        <form id="newGroup" class="row-actions">
          <input name="name" placeholder="group name" required />
          <button class="pill-btn primary" type="submit">Create</button>
        </form>
      </div>
    </div>
    <div class="surface">
      <div class="panel-head">Groups</div>
      <div class="panel-pad">
        <table>
          <thead><tr><th>Name</th><th>Members</th><th></th></tr></thead>
          <tbody>${rows || `<tr><td colspan="3" class="muted">No groups</td></tr>`}</tbody>
        </table>
      </div>
    </div>`;
  $("#newGroup").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/groups", {
        method: "POST",
        body: JSON.stringify({ name: new FormData(e.target).get("name") }),
      });
      await renderGroups();
    } catch (err) {
      showErr(err.message);
    }
  });
  document.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`Delete group ${btn.dataset.del}?`)) return;
      try {
        await api(`/api/groups/${encodeURIComponent(btn.dataset.del)}`, { method: "DELETE" });
        await renderGroups();
      } catch (err) {
        showErr(err.message);
      }
    });
  });
  document.querySelectorAll("[data-members]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const csv = prompt("Comma-separated enrolled host names");
      if (csv == null) return;
      try {
        await api(`/api/groups/${encodeURIComponent(btn.dataset.members)}/members`, {
          method: "POST",
          body: JSON.stringify({ members: csv }),
        });
        await renderGroups();
      } catch (err) {
        showErr(err.message);
      }
    });
  });
}

async function renderHub() {
  const st = await api("/api/status");
  $("#tab-hub").innerHTML = `
    <div class="surface">
      <div class="panel-head">Hub</div>
      <div class="panel-pad">
        <p>Initialized: <strong>${st.initialized ? "yes" : "no"}</strong></p>
        <p class="mono muted">${esc(st.hub_id || "")}</p>
        <p class="muted">${esc(st.root || "")}</p>
        <p class="muted">Spokes: ${(st.spokes || []).length} · Groups: ${(st.groups || []).length}</p>
        <div class="row-actions" style="margin-top:12px">
          ${st.initialized ? "" : `<button id="initHub" class="pill-btn primary">Initialize hub</button>`}
          <button id="opencode" class="pill-btn">Write OpenCode config</button>
        </div>
        <p id="hubMsg" class="muted"></p>
      </div>
    </div>`;
  const init = $("#initHub");
  if (init) {
    init.addEventListener("click", async () => {
      try {
        await api("/api/hub/init", { method: "POST", body: JSON.stringify({ name: "hub-01" }) });
        await renderHub();
      } catch (err) {
        showErr(err.message);
      }
    });
  }
  $("#opencode").addEventListener("click", async () => {
    try {
      const r = await api("/api/opencode", { method: "POST" });
      $("#hubMsg").textContent = `wrote ${r.path}`;
    } catch (err) {
      showErr(err.message);
    }
  });
}

async function renderOperators() {
  const { operators } = await api("/api/operators");
  const rows = (operators || [])
    .map(
      (o) => `<tr><td>${esc(o.email)}</td><td class="muted">${esc(o.createdAt)}</td></tr>`,
    )
    .join("");
  $("#tab-operators").innerHTML = `
    <div class="surface">
      <div class="panel-head">Operators</div>
      <div class="panel-pad">
        <p class="lede" style="margin-top:0">Accounts are local to this hub. Not shared with mcp-flow or other products.</p>
        <table>
          <thead><tr><th>Email</th><th>Created</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <form id="addOp" class="row-actions" style="margin-top:12px">
          <input name="email" type="email" placeholder="email" required />
          <input name="password" type="password" placeholder="password" minlength="8" required />
          <button class="pill-btn primary" type="submit">Add</button>
        </form>
      </div>
    </div>`;
  $("#addOp").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api("/api/operators", {
        method: "POST",
        body: JSON.stringify({ email: fd.get("email"), password: fd.get("password") }),
      });
      await renderOperators();
    } catch (err) {
      showErr(err.message);
    }
  });
}

async function refresh() {
  showErr("");
  const tab = document.querySelector(".seg-btn.active")?.dataset.tab || "servers";
  if (tab === "servers") await renderServers();
  if (tab === "groups") await renderGroups();
  if (tab === "hub") await renderHub();
  if (tab === "operators") await renderOperators();
}

document.querySelectorAll(".seg-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
    void refresh();
  });
});

$("#logout").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  location.replace("/login");
});

(async () => {
  const me = await fetch("/api/auth/me").then((r) => (r.ok ? r.json() : null));
  if (!me) {
    const st = await fetch("/api/auth/status").then((r) => r.json());
    location.replace(st.setupRequired ? "/setup" : "/login");
    return;
  }
  csrf = me.csrf || "";
  $("#who").textContent = me.operator.email;
  await refresh();
})();
