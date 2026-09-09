const $ = (s) => document.querySelector(s);
const errEl = $("#err");
const TOKEN_KEY = "ansible_flow_admin_token";

function token() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

function setToken(t) {
  sessionStorage.setItem(TOKEN_KEY, t);
}

function showErr(msg) {
  errEl.hidden = !msg;
  errEl.textContent = msg || "";
}

async function api(path, opts = {}) {
  const t = token();
  if (!t) throw new Error("Set admin token first");
  const res = await fetch(path, {
    ...opts,
    headers: {
      Authorization: `Bearer ${t}`,
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });
  const text = await res.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { raw: text };
  }
  if (!res.ok) {
    throw new Error(body.error || res.statusText || String(res.status));
  }
  return body;
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function surface(title, bodyHtml, rightTitle = "") {
  return `
    <div class="surface">
      <div class="panel-head">
        <span class="title">${esc(title)}</span>
        ${rightTitle ? `<span class="title mute">${esc(rightTitle)}</span>` : ""}
      </div>
      <div class="panel-pad">${bodyHtml}</div>
    </div>`;
}

async function renderStatus() {
  const st = await api("/v1/status");
  const health = await fetch("/health").then((r) => r.json());
  const ok = health?.ok !== false;
  $("#tab-status").innerHTML = `
    ${surface(
      "Hub",
      `
      <div class="stat-grid">
        <div class="stat"><span class="label">Name</span><span class="value">${esc(st.name)}</span></div>
        <div class="stat"><span class="label">Hub id</span><span class="value mono">${esc(st.hub_id)}</span></div>
        <div class="stat"><span class="label">Spokes</span><span class="value">${esc((st.spokes || []).length)}</span></div>
        <div class="stat"><span class="label">Targets</span><span class="value">${esc((st.targets || []).length)}</span></div>
        <div class="stat"><span class="label">Groups</span><span class="value">${esc((st.groups || []).length)}</span></div>
        <div class="stat"><span class="label">Health</span><span class="value"><span class="pill ${ok ? "on" : "deny"}">${ok ? "ok" : "degraded"}</span></span></div>
      </div>
    `,
      "inventory",
    )}
    ${surface(
      "Paths",
      `
      <div class="kv">
        <div class="kv-row"><span class="k">Inventory</span><span class="v mono">${esc(st.inventory)}</span></div>
        <div class="kv-row"><span class="k">Root</span><span class="v mono">${esc(st.root)}</span></div>
        <div class="kv-row"><span class="k">Known hosts</span><span class="v mono">${esc(st.known_hosts)}</span></div>
        <div class="kv-row"><span class="k">Version</span><span class="v mono">${esc(st.version || health.version)}</span></div>
      </div>
      <details class="fold"><summary>Raw /health</summary><pre>${esc(JSON.stringify(health, null, 2))}</pre></details>
    `,
      "live",
    )}`;
}

function nodeRows(nodes, kind) {
  if (!nodes.length) return `<p class="empty">No ${esc(kind)} yet.</p>`;
  return `
    <table class="data">
      <thead><tr><th>Name</th><th>Host</th><th>Port</th><th>User</th><th>Groups</th><th></th></tr></thead>
      <tbody>
        ${nodes
          .map((n) => {
            const name = n.name || n;
            return `<tr>
              <td class="mono">${esc(name)}</td>
              <td class="mono">${esc(n.ansible_host || "")}</td>
              <td class="mono">${esc(n.ansible_port ?? "")}</td>
              <td class="mono">${esc(n.ansible_user || "")}</td>
              <td>${(n.groups || []).map((g) => `<span class="pill accent">${esc(g)}</span>`).join(" ") || "—"}</td>
              <td class="row-actions">
                ${
                  kind === "spokes"
                    ? `<button type="button" class="pill-btn ghost" data-ping="${esc(name)}">Ping</button>`
                    : ""
                }
                <button type="button" class="pill-btn ghost" data-edit="${esc(name)}">Edit</button>
                <button type="button" class="pill-btn danger" data-del="${esc(name)}">${kind === "spokes" ? "Revoke" : "Remove"}</button>
              </td>
            </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;
}

async function renderServers() {
  const [{ nodes }, st] = await Promise.all([api("/v1/nodes"), api("/v1/status")]);
  $("#tab-servers").innerHTML = `
    ${surface(
      "Invite spoke",
      `
      <div class="form-grid">
        <div class="form-field"><label class="field-label" for="invName">Name</label><input id="invName" placeholder="web-01" /></div>
        <div class="form-field"><label class="field-label" for="invTtl">TTL seconds</label><input id="invTtl" value="900" /></div>
        <div class="form-field"><label class="field-label" for="invHub">Join hub</label><input id="invHub" placeholder="mcp-join@hub" /></div>
        <div class="form-field"><label class="field-label" for="invAddr">Public addr</label><input id="invAddr" placeholder="web-01" /></div>
        <button type="button" id="issueTok" class="pill-btn primary">Issue token</button>
      </div>
      <div id="inviteOut"></div>
    `,
      "one-time",
    )}
    ${surface("Enrolled spokes", nodeRows(nodes || [], "spokes"), `${(nodes || []).length} · ${(st.spokes || []).join(", ") || "empty"}`)}
    ${surface(
      "Edit spoke",
      `
      <div class="form-grid">
        <div class="form-field"><label class="field-label" for="edName">Name</label><input id="edName" /></div>
        <div class="form-field"><label class="field-label" for="edHost">ansible_host</label><input id="edHost" /></div>
        <div class="form-field"><label class="field-label" for="edPort">port</label><input id="edPort" /></div>
        <div class="form-field"><label class="field-label" for="edUser">user</label><input id="edUser" /></div>
        <button type="button" id="saveNode" class="pill-btn primary">Save</button>
      </div>
    `,
      "update_node",
    )}`;

  $("#issueTok")?.addEventListener("click", async () => {
    try {
      const body = {
        name: $("#invName").value.trim(),
        ttl_seconds: Number($("#invTtl").value || 900),
      };
      if ($("#invHub").value.trim()) body.hub = $("#invHub").value.trim();
      if ($("#invAddr").value.trim()) body.public_addr = $("#invAddr").value.trim();
      const issued = await api("/v1/tokens", { method: "POST", body: JSON.stringify(body) });
      $("#inviteOut").innerHTML = `
        <div class="token-box">
          <p class="dim">Shown once. Copy now.</p>
          <pre>${esc(issued.token)}</pre>
          <p class="field-label" style="margin-top:10px">Join command</p>
          <pre>${esc(issued.join_command)}</pre>
        </div>`;
    } catch (e) {
      showErr(e.message);
    }
  });

  $("#saveNode")?.addEventListener("click", async () => {
    try {
      const name = $("#edName").value.trim();
      const payload = {};
      if ($("#edHost").value.trim()) payload.ansible_host = $("#edHost").value.trim();
      if ($("#edPort").value.trim()) payload.ansible_port = Number($("#edPort").value);
      if ($("#edUser").value.trim()) payload.ansible_user = $("#edUser").value.trim();
      await api(`/v1/nodes/${encodeURIComponent(name)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      await refresh();
    } catch (e) {
      showErr(e.message);
    }
  });

  $("#tab-servers").querySelectorAll("[data-edit]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const n = (nodes || []).find((x) => x.name === btn.getAttribute("data-edit"));
      $("#edName").value = btn.getAttribute("data-edit") || "";
      $("#edHost").value = n?.ansible_host || "";
      $("#edPort").value = n?.ansible_port ?? "";
      $("#edUser").value = n?.ansible_user || "";
    });
  });
  $("#tab-servers").querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.getAttribute("data-del");
      if (!confirm(`Revoke spoke ${name}?`)) return;
      try {
        await api(`/v1/nodes/${encodeURIComponent(name)}`, { method: "DELETE" });
        await refresh();
      } catch (e) {
        showErr(e.message);
      }
    });
  });
  $("#tab-servers").querySelectorAll("[data-ping]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const name = btn.getAttribute("data-ping");
        const res = await api(`/v1/nodes/${encodeURIComponent(name)}/ping`, { method: "POST", body: "{}" });
        alert(res.ok ? `Ping ok: ${name}` : `Ping failed: ${res.error || res.stderr || "error"}`);
      } catch (e) {
        showErr(e.message);
      }
    });
  });
}

async function renderTargets() {
  const { targets } = await api("/v1/targets");
  $("#tab-targets").innerHTML = `
    ${surface(
      "Register target",
      `
      <p class="dim" style="margin-bottom:10px">Ansible-only host. Do not enter passwords — use hub Ansible cfg or path refs.</p>
      <div class="form-grid">
        <div class="form-field"><label class="field-label" for="tgName">Name</label><input id="tgName" placeholder="win-01" /></div>
        <div class="form-field"><label class="field-label" for="tgHost">ansible_host</label><input id="tgHost" /></div>
        <div class="form-field"><label class="field-label" for="tgConn">connection</label><input id="tgConn" value="ssh" /></div>
        <div class="form-field"><label class="field-label" for="tgPort">port</label><input id="tgPort" /></div>
        <div class="form-field"><label class="field-label" for="tgUser">user</label><input id="tgUser" /></div>
        <button type="button" id="addTarget" class="pill-btn primary">Register</button>
      </div>
    `,
      "no secrets",
    )}
    ${surface("Registered targets", nodeRows(targets || [], "targets"), "no spoke_call")}
    ${surface(
      "Edit target",
      `
      <div class="form-grid">
        <div class="form-field"><label class="field-label" for="teName">Name</label><input id="teName" /></div>
        <div class="form-field"><label class="field-label" for="teHost">ansible_host</label><input id="teHost" /></div>
        <div class="form-field"><label class="field-label" for="teConn">connection</label><input id="teConn" /></div>
        <div class="form-field"><label class="field-label" for="tePort">port</label><input id="tePort" /></div>
        <div class="form-field"><label class="field-label" for="teUser">user</label><input id="teUser" /></div>
        <button type="button" id="saveTarget" class="pill-btn primary">Save</button>
      </div>
    `,
      "update_target",
    )}`;

  $("#addTarget")?.addEventListener("click", async () => {
    try {
      const payload = {
        name: $("#tgName").value.trim(),
        ansible_host: $("#tgHost").value.trim(),
        ansible_connection: $("#tgConn").value.trim() || "ssh",
      };
      if ($("#tgPort").value.trim()) payload.ansible_port = Number($("#tgPort").value);
      if ($("#tgUser").value.trim()) payload.ansible_user = $("#tgUser").value.trim();
      await api("/v1/targets", { method: "POST", body: JSON.stringify(payload) });
      await refresh();
    } catch (e) {
      showErr(e.message);
    }
  });
  $("#saveTarget")?.addEventListener("click", async () => {
    try {
      const name = $("#teName").value.trim();
      const payload = {};
      if ($("#teHost").value.trim()) payload.ansible_host = $("#teHost").value.trim();
      if ($("#teConn").value.trim()) payload.ansible_connection = $("#teConn").value.trim();
      if ($("#tePort").value.trim()) payload.ansible_port = Number($("#tePort").value);
      if ($("#teUser").value.trim()) payload.ansible_user = $("#teUser").value.trim();
      await api(`/v1/targets/${encodeURIComponent(name)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      await refresh();
    } catch (e) {
      showErr(e.message);
    }
  });
  $("#tab-targets").querySelectorAll("[data-edit]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const n = (targets || []).find((x) => x.name === btn.getAttribute("data-edit"));
      $("#teName").value = btn.getAttribute("data-edit") || "";
      $("#teHost").value = n?.ansible_host || "";
      $("#teConn").value = n?.ansible_connection || "";
      $("#tePort").value = n?.ansible_port ?? "";
      $("#teUser").value = n?.ansible_user || "";
    });
  });
  $("#tab-targets").querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.getAttribute("data-del");
      if (!confirm(`Remove target ${name}?`)) return;
      try {
        await api(`/v1/targets/${encodeURIComponent(name)}`, { method: "DELETE" });
        await refresh();
      } catch (e) {
        showErr(e.message);
      }
    });
  });
}

async function renderGroups() {
  const [{ groups }, st] = await Promise.all([api("/v1/groups"), api("/v1/status")]);
  const members = [...(st.spokes || []), ...(st.targets || [])];
  $("#tab-groups").innerHTML = `
    ${surface(
      "Create group",
      `
      <div class="form-grid">
        <div class="form-field"><label class="field-label" for="grName">Name</label><input id="grName" placeholder="prod" /></div>
        <button type="button" id="addGroup" class="pill-btn primary">Create</button>
      </div>
    `,
      "custom",
    )}
    ${surface(
      "Groups",
      (groups || []).length
        ? `<table class="data"><thead><tr><th>Name</th><th>Members</th><th></th></tr></thead><tbody>
        ${(groups || [])
          .map(
            (g) => `<tr>
              <td class="mono">${esc(g.name)}</td>
              <td>${(g.hosts || []).map((h) => `<span class="pill vault">${esc(h)}</span>`).join(" ") || "—"}</td>
              <td class="row-actions">
                <button type="button" class="pill-btn ghost" data-mem="${esc(g.name)}">Members</button>
                <button type="button" class="pill-btn danger" data-gdel="${esc(g.name)}">Delete</button>
              </td>
            </tr>`,
          )
          .join("")}
        </tbody></table>`
        : `<p class="empty">No custom groups.</p>`,
      `${(groups || []).length}`,
    )}
    ${surface(
      "Set members",
      `
      <div class="form-field"><label class="field-label" for="gmName">Group</label><input id="gmName" /></div>
      <div style="margin:10px 0">
        ${
          members.length
            ? members
                .map((n) => `<label class="form-check"><input type="checkbox" data-host="${esc(n)}" /> <span class="mono">${esc(n)}</span></label>`)
                .join("")
            : `<span class="muted">Enroll a spoke or register a target first</span>`
        }
      </div>
      <button type="button" id="saveMembers" class="pill-btn primary">Save members</button>
    `,
      "enrolled only",
    )}`;

  $("#addGroup")?.addEventListener("click", async () => {
    try {
      await api("/v1/groups", { method: "POST", body: JSON.stringify({ name: $("#grName").value.trim() }) });
      await refresh();
    } catch (e) {
      showErr(e.message);
    }
  });
  $("#saveMembers")?.addEventListener("click", async () => {
    try {
      const name = $("#gmName").value.trim();
      const hosts = [...document.querySelectorAll("#tab-groups [data-host]:checked")].map((el) =>
        el.getAttribute("data-host"),
      );
      await api(`/v1/groups/${encodeURIComponent(name)}/members`, {
        method: "PUT",
        body: JSON.stringify({ hosts }),
      });
      await refresh();
    } catch (e) {
      showErr(e.message);
    }
  });
  $("#tab-groups").querySelectorAll("[data-gdel]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.getAttribute("data-gdel");
      if (!confirm(`Delete group ${name}?`)) return;
      try {
        await api(`/v1/groups/${encodeURIComponent(name)}`, { method: "DELETE" });
        await refresh();
      } catch (e) {
        showErr(e.message);
      }
    });
  });
  $("#tab-groups").querySelectorAll("[data-mem]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.getAttribute("data-mem");
      $("#gmName").value = name;
      const g = (groups || []).find((x) => x.name === name);
      const set = new Set(g?.hosts || []);
      document.querySelectorAll("#tab-groups [data-host]").forEach((el) => {
        el.checked = set.has(el.getAttribute("data-host"));
      });
    });
  });
}

async function renderAudit() {
  const { events } = await api("/v1/audit?limit=80");
  const rows = events || [];
  $("#tab-audit").innerHTML = surface(
    "Audit",
    rows.length
      ? `<table class="data"><thead><tr><th>Time</th><th>Event</th><th>Detail</th></tr></thead><tbody>
        ${rows
          .map((e) => {
            const { ts, event, ...rest } = e;
            return `<tr><td class="mono">${esc(ts)}</td><td>${esc(event)}</td><td class="mono">${esc(JSON.stringify(rest))}</td></tr>`;
          })
          .join("")}
      </tbody></table>`
      : `<p class="empty">No audit events.</p>`,
    "redacted",
  );
}

const renderers = {
  status: renderStatus,
  servers: renderServers,
  targets: renderTargets,
  groups: renderGroups,
  audit: renderAudit,
};

let current = "status";

async function refresh() {
  showErr("");
  try {
    await renderers[current]();
  } catch (e) {
    showErr(e.message);
  }
}

document.querySelectorAll("[data-tab]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    current = btn.getAttribute("data-tab");
    document.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${current}`));
    await refresh();
  });
});

$("#saveToken")?.addEventListener("click", async () => {
  setToken($("#token").value.trim());
  await refresh();
});

$("#refresh")?.addEventListener("click", refresh);

if (token()) {
  $("#token").value = token();
  refresh();
}
