# Hub admin UI

Vite + React + Tailwind + shadcn/ui for the hub operator console. The Python admin server serves the compiled files from `src/ansible_flow_mcp/admin/static`.

```bash
cd admin-ui
npm ci
npm run build
```

Entry URLs stay `/admin/`, `/admin/app.js`, and `/admin/styles.css`. Font files are under `/admin/assets/`. The `/v1/` JSON API is unchanged.

```bash
ansible-flow-mcp hub admin
# http://127.0.0.1:8789/admin/
```

Paste the token from `ANSIBLE_FLOW_ADMIN_TOKEN` or `$HUB_DIR/admin.token` (sessionStorage only).

`npm run dev` serves the UI on port 5173 at `/admin/` and proxies `/v1` and `/health` to `127.0.0.1:8789`.
