#!/usr/bin/env bash
# Capture campaign frames → docs/images/campaign-*.png
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$(cd "$ROOT/../images" && pwd)"
WORKDIR="${CAMPAIGN_CAPTURE_DIR:-/tmp/opencode/campaign-capture}"
mkdir -p "$OUT" "$WORKDIR"

if [[ ! -d "$WORKDIR/node_modules/playwright" ]]; then
  echo "Installing playwright into $WORKDIR …"
  (
    cd "$WORKDIR"
    npm init -y >/dev/null 2>&1
    npm install playwright@1.49.0
    npx playwright install chromium
  )
fi

export CAMPAIGN_ROOT="$ROOT"
export CAMPAIGN_OUT="$OUT"
export NODE_PATH="$WORKDIR/node_modules${NODE_PATH:+:$NODE_PATH}"

node <<'NODE'
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");
const http = require("http");

const root = process.env.CAMPAIGN_ROOT;
const outDir = process.env.CAMPAIGN_OUT;

const frames = [
  ["hero", "campaign-hero.png"],
  ["why", "campaign-why.png"],
  ["agent-loop", "campaign-agent-loop.png"],
  ["hub-spoke", "campaign-hub-spoke.png"],
  ["operator", "campaign-operator.png"],
];

const mime = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

const server = http.createServer((req, res) => {
  let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
  if (urlPath === "/") urlPath = "/index.html";
  const file = path.normalize(path.join(root, urlPath));
  if (!file.startsWith(root)) {
    res.writeHead(403);
    res.end("forbidden");
    return;
  }
  fs.readFile(file, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end("not found");
      return;
    }
    res.writeHead(200, {
      "Content-Type": mime[path.extname(file)] || "application/octet-stream",
    });
    res.end(data);
  });
});

(async () => {
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const { port } = server.address();
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1500, height: 980 },
    deviceScaleFactor: 2,
  });

  for (const [name, file] of frames) {
    const url = `http://127.0.0.1:${port}/frames/${name}.html`;
    await page.goto(url, { waitUntil: "networkidle", timeout: 90000 });
    await page.waitForTimeout(800);
    const el = await page.$("#frame");
    if (!el) throw new Error(`#frame missing on ${name}`);
    const dest = path.join(outDir, file);
    await el.screenshot({ path: dest, type: "png" });
    console.log("wrote", dest);
  }

  await browser.close();
  server.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
NODE
