# Ansible Flow catalog factory

Factory-style **TUI + queue** that scrapes **top Ansible Galaxy collections** (by download count), expands their modules, and generates `catalog/gallery.json` + `catalog/schemas/*.json` — the same role OpenFlow’s node factory plays for n8n types.

## Quick start

```bash
cd ansible-flow-mcp
python scripts/factory/tui.py
```

Or headless:

```bash
# 1) Scan top 40 Galaxy collections → module list
python scripts/factory/scrape_galaxy.py --top 40 --enqueue

# 2) Generate schemas + merge gallery (ansible-doc when available)
python scripts/factory/queue_worker.py --concurrency 4
```

## Mental model

```text
Galaxy UI search (order_by=-download_count)
  → top-N collections + embedded module inventory
  → optional ansible.builtin via ansible-doc -l
  → cherry-pick / enqueue FQCNs
  → worker: ansible-doc -j → schema JSON  (else Galaxy stub)
  → upsert catalog/gallery.json + schemas/
  → optional allowlist append (collections-allowlist.yml)
```

## TUI screens (Tab)

| Mode | What |
|------|------|
| **SCAN** | Fetch top-N collections; Space toggle; `e` enqueue modules from selected collections |
| **LIST** | Module inventory; Space pick; `e`/`E` enqueue; `n` enqueue + start worker; `/` filter |
| **QUEUE** | Job statuses; **S** start worker; **X** stop; `r` requeue failed |
| **SETTINGS** | `topN`, concurrency, namespace filter, autoAllowlist, … |
| **LOG** | Tail `scripts/factory/.jobs/worker.log` |

### Keys (summary)

| Key | Action |
|-----|--------|
| **Tab** | Cycle screens |
| **Enter** (SCAN) | Run Galaxy top-N scrape |
| **Space** | Toggle selection |
| **e** / **E** | Enqueue selected / all visible |
| **S** / **X** | Start / stop queue worker |
| **k** (LIST) | Toggle hide modules already in gallery+schema |
| **?** | Help |
| **q** | Quit TUI (worker keeps running) |

## Settings

`scripts/factory/.jobs/settings.json` (created on first save):

| Key | Default | Meaning |
|-----|---------|---------|
| `topN` | 40 | Collections to pull from Galaxy |
| `concurrency` | 4 | Parallel schema jobs |
| `modulesPerCollection` | 0 | Cap modules per collection (0=all) |
| `namespaceFilter` | `""` | e.g. `community,amazon,ansible` |
| `includeBuiltin` | true | Also list `ansible.builtin.*` via ansible-doc |
| `preferAnsibleDoc` | true | Full argSpec when `ansible-doc` is on PATH |
| `autoAllowlist` | true | Append new collections to allowlist YAML |
| `denyFreeform` | true | Skip command/shell/raw/script |
| `minDownloadCount` | 0 | Galaxy download floor |

## Layout

```text
scripts/factory/
  tui.py              # curses TUI
  scrape_galaxy.py    # CLI scan
  queue_worker.py     # background schema worker
  lib/
    galaxy_client.py  # Galaxy _ui/v1/search API
    job_store.py      # queue + scans under .jobs/
    schema_gen.py     # ansible-doc → slim schema
    catalog_io.py     # gallery + allowlist merge
  .jobs/              # gitignored runtime state
    scans/<id>/
    queue/*.json
    worker.log
```

## Notes

- **ansible.builtin** is not a Galaxy collection; it is discovered with `ansible-doc -l` when installed.
- Without `ansible-doc`, the worker still writes **stub** schemas (description + doc URL, empty options) so the gallery grows from Galaxy alone.
- Free-form modules stay denied (aligned with `docs/SECURITY.md`).
- Dual-track with OpenFlow Ansible gallery — same FQCN / slim schema shape as `scripts/generate_catalog.py`.

## Related

- `scripts/generate_catalog.py` — regenerate from local `ansible-doc` only (no Galaxy ranking)
- OpenFlow factory TUI: `OpenFlow-r2/scripts/factory/tui.py`
