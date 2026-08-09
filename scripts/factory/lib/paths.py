from __future__ import annotations

from pathlib import Path

FACTORY = Path(__file__).resolve().parents[1]
ROOT = FACTORY.parents[1]
JOBS = FACTORY / ".jobs"
SCANS = JOBS / "scans"
QUEUE = JOBS / "queue"
NODES = JOBS / "nodes"
SETTINGS_PATH = JOBS / "settings.json"
WORKER_PID = JOBS / "worker.pid"
WORKER_LOG = JOBS / "worker.log"
CATALOG = ROOT / "catalog"
GALLERY = CATALOG / "gallery.json"
SCHEMAS = CATALOG / "schemas"
ALLOWLIST = CATALOG / "collections-allowlist.yml"

DEFAULT_SETTINGS: dict = {
    "topN": 40,
    "modulesPerCollection": 0,  # 0 = all modules
    "concurrency": 2,  # keep low — gallery lock serializes writes
    "galaxyPageSize": 20,
    "galaxyBase": "https://galaxy.ansible.com",
    "includeBuiltin": True,
    "autoAllowlist": True,
    "preferAnsibleDoc": True,
    "denyFreeform": True,
    "minDownloadCount": 0,
    "namespaceFilter": "",  # comma namespaces e.g. community,ansible,amazon
    "outCatalog": str(CATALOG),
    # HTTP / proxy
    "useProxy": False,
    "proxy": "",  # fixed proxy URL e.g. socks5h://host:1080 or http://host:8080
    "proxyListUrl": "https://databay.com/free-proxy-list/socks5.txt",
    "proxyProbeLimit": 40,
    "proxyProbeTimeout": 10,
    "httpTimeout": 45,
    "httpRetries": 3,
    "galaxyPause": 0.15,
    # schema quality + collections
    "requireRealSchema": True,  # never mark galaxy-stub as done
    "autoInstallCollections": True,
    "collectionsPath": "",  # default: scripts/factory/.jobs/collections
    "skipCollections": [],  # e.g. ["oracle.oci"]
    "installTimeoutSec": 600,
}

DEFAULT_DENY = frozenset(
    {
        "ansible.builtin.shell",
        "ansible.builtin.command",
        "ansible.builtin.raw",
        "ansible.builtin.script",
    }
)
