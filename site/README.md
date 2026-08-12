# Marketing site

Static multi-page campaign site for **ansible-flow-mcp**.

## Pages

| File | Story |
| --- | --- |
| `index.html` | Hero · three acts |
| `why.html` | Act I — enrollment is the perimeter |
| `how.html` | Act II — ritual + **Schema Lab** (full gallery + schemas) |
| `fabric.html` | Act III — hub/spoke |
| `security.html` | Controls + residual risk |
| `start.html` | Install / lab / MCP |

## Local preview

Schema Lab needs HTTP (not `file://`) and `catalog/` beside the site:

```bash
python3 scripts/generate_browse.py   # slim browse shards for lazy search
./scripts/site_preview.sh
# http://127.0.0.1:8765/how.html
```

### Schema Lab data layout

| Path | Role |
| --- | --- |
| `catalog/browse/manifest.json` + `shard-*.json` | **Lazy** slim index (site search / pagination) |
| `catalog/schemas/{fqcn}.json` | Full slim argSpec (fetched when you select a module) |
| `catalog/gallery.json` | Full gallery SoT for MCP tools; site fallback only |

Browse is generated; do not hand-edit shards. Search runs in a Web Worker with pagination + list/card views.

## Deploy

GitHub Actions workflow `.github/workflows/pages.yml` publishes:

```text
site/*  +  catalog/browse/  +  catalog/gallery.json  +  catalog/schemas/
```

to GitHub Pages. Enable **Settings → Pages → Source: GitHub Actions**.

Project URL shape: `https://<owner>.github.io/ansible-flow-mcp/`.

## Design

Copper Busbar tokens shared with `docs/campaign/` (screenshot storyboard). Do not replace campaign frames with this site — both stay.
