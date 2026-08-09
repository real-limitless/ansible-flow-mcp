# Campaign storyboard

Static HTML frames used to produce README marketing screenshots.

## Frames

| File | Output PNG |
| --- | --- |
| `frames/hero.html` | `docs/images/campaign-hero.png` |
| `frames/why.html` | `docs/images/campaign-why.png` |
| `frames/agent-loop.html` | `docs/images/campaign-agent-loop.png` |
| `frames/hub-spoke.html` | `docs/images/campaign-hub-spoke.png` |
| `frames/operator.html` | `docs/images/campaign-operator.png` |

## Capture

```bash
cd docs/campaign
./capture.sh
```

Requires network once for Google Fonts (or frames fall back to system fonts). Uses Playwright via `npx` when available.

Manual: open a frame in a browser at 100% zoom and screenshot the 1440×900 `.canvas`.
