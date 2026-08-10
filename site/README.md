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
./scripts/site_preview.sh
# http://127.0.0.1:8765/
```

## Deploy

GitHub Actions workflow `.github/workflows/pages.yml` publishes:

```text
site/*  +  catalog/gallery.json  +  catalog/schemas/
```

to GitHub Pages. Enable **Settings → Pages → Source: GitHub Actions**.

Project URL shape: `https://<owner>.github.io/ansible-flow-mcp/`.

## Design

Copper Busbar tokens shared with `docs/campaign/` (screenshot storyboard). Do not replace campaign frames with this site — both stay.
