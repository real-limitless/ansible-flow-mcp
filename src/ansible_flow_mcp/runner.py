from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from ansible_flow_mcp.security import SecurityPolicy, load_policy, redact_secrets

RunFn = Callable[[list[str], dict[str, str], float], tuple[int, str, str]]


@dataclass
class HostResult:
    host: str
    ok: bool
    changed: bool
    failed: bool
    unreachable: bool
    skipped: bool
    msg: str | None
    rc: int | None
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "ok": self.ok,
            "changed": self.changed,
            "failed": self.failed,
            "unreachable": self.unreachable,
            "skipped": self.skipped,
            "msg": self.msg,
            "rc": self.rc,
            "result": self.result,
        }


@dataclass
class RunModuleResult:
    module: str
    check_mode: bool
    exit_code: int
    hosts: list[HostResult]
    raw_stdout: str
    raw_stderr: str
    argv: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "checkMode": self.check_mode,
            "exitCode": self.exit_code,
            "hosts": [h.to_dict() for h in self.hosts],
            "stdout": self.raw_stdout,
            "stderr": self.raw_stderr,
            "argv": self.argv,
            "failed": self.exit_code != 0 or any(h.failed or h.unreachable for h in self.hosts),
        }


def format_module_args(args: dict[str, Any] | None) -> str | None:
    if not args:
        return None
    # Prefer JSON object form accepted by ansible -a for complex values.
    return json.dumps(args, separators=(",", ":"), ensure_ascii=False)


def build_ansible_argv(
    *,
    module: str,
    hosts: str = "localhost",
    args: dict[str, Any] | None = None,
    inventory: str | None = None,
    check_mode: bool = False,
    become: bool = False,
    become_user: str | None = None,
    connection: str | None = None,
    extra_vars: dict[str, Any] | None = None,
    verbosity: int = 0,
) -> list[str]:
    host_pattern = (hosts or "localhost").strip() or "localhost"
    inv = inventory
    if not inv:
        # Inline inventory so single-host patterns work without /etc/ansible/hosts
        inv = f"{host_pattern},"

    argv: list[str] = [
        "ansible",
        host_pattern,
        "-m",
        module,
        "-i",
        inv,
    ]
    args_str = format_module_args(args)
    if args_str is not None:
        argv.extend(["-a", args_str])
    if check_mode:
        argv.append("--check")
    if become:
        argv.append("--become")
    if become_user:
        argv.extend(["--become-user", become_user])
    if connection:
        argv.extend(["-c", connection])
    elif host_pattern in {"localhost", "127.0.0.1"} and inventory is None:
        argv.extend(["-c", "local"])
    if extra_vars:
        argv.extend(["-e", json.dumps(extra_vars, separators=(",", ":"), ensure_ascii=False)])
    verb = max(0, min(int(verbosity or 0), 4))
    if verb:
        argv.append("-" + ("v" * verb))
    return argv


def parse_json_callback(stdout: str) -> list[HostResult]:
    text = (stdout or "").strip()
    if not text:
        return []
    # Callback may emit multiple JSON documents; take the last object-looking blob.
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []

    hosts: list[HostResult] = []
    plays = data.get("plays") if isinstance(data, dict) else None
    if not isinstance(plays, list):
        return hosts

    for play in plays:
        if not isinstance(play, dict):
            continue
        tasks = play.get("tasks") or []
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            host_map = task.get("hosts") or {}
            if not isinstance(host_map, dict):
                continue
            for host, raw in host_map.items():
                if not isinstance(raw, dict):
                    raw = {"msg": str(raw)}
                failed = bool(raw.get("failed")) or bool(raw.get("unreachable"))
                unreachable = bool(raw.get("unreachable"))
                skipped = bool(raw.get("skipped"))
                ok = not failed and not skipped
                changed = bool(raw.get("changed"))
                msg = raw.get("msg")
                if msg is not None:
                    msg = str(msg)
                rc = raw.get("rc")
                if rc is not None:
                    try:
                        rc = int(rc)
                    except (TypeError, ValueError):
                        rc = None
                cleaned = redact_secrets(dict(raw))
                hosts.append(
                    HostResult(
                        host=str(host),
                        ok=ok,
                        changed=changed,
                        failed=failed,
                        unreachable=unreachable,
                        skipped=skipped,
                        msg=msg,
                        rc=rc,
                        result=cleaned,
                    )
                )
    return hosts


def _default_run(argv: list[str], env: dict[str, str], timeout: float) -> tuple[int, str, str]:
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def run_module(
    module: str,
    *,
    args: dict[str, Any] | None = None,
    hosts: str = "localhost",
    inventory: str | None = None,
    check_mode: bool = False,
    become: bool = False,
    become_user: str | None = None,
    connection: str | None = None,
    extra_vars: dict[str, Any] | None = None,
    verbosity: int = 0,
    timeout: float | None = None,
    policy: SecurityPolicy | None = None,
    run_fn: RunFn | None = None,
) -> RunModuleResult:
    pol = policy or load_policy()
    fqcn = pol.assert_module_allowed(module)

    require_check = os.environ.get("ANSIBLE_FLOW_REQUIRE_CHECK", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if require_check and not check_mode:
        # Soft policy: still allow, but callers should prefer check first.
        pass

    argv = build_ansible_argv(
        module=fqcn,
        hosts=hosts,
        args=args,
        inventory=inventory or os.environ.get("ANSIBLE_FLOW_INVENTORY"),
        check_mode=check_mode,
        become=become,
        become_user=become_user,
        connection=connection,
        extra_vars=extra_vars,
        verbosity=verbosity,
    )

    env = os.environ.copy()
    env.setdefault("ANSIBLE_STDOUT_CALLBACK", "json")
    env.setdefault("ANSIBLE_RETRY_FILES_ENABLED", "False")
    env.setdefault("ANSIBLE_HOST_KEY_CHECKING", "False")
    # Avoid interactive prompts
    env.setdefault("ANSIBLE_DEPRECATION_WARNINGS", "False")

    t = float(timeout if timeout is not None else os.environ.get("ANSIBLE_FLOW_TIMEOUT", "120"))
    t = max(5.0, min(t, 3600.0))

    runner = run_fn or _default_run
    code, stdout, stderr = runner(argv, env, t)
    host_results = parse_json_callback(stdout)

    # If JSON parse failed but process failed, synthesize a host error
    if not host_results and code != 0:
        host_results = [
            HostResult(
                host=(hosts or "localhost").split(",")[0].strip() or "localhost",
                ok=False,
                changed=False,
                failed=True,
                unreachable=False,
                skipped=False,
                msg=(stderr or stdout or f"ansible exited {code}")[:2000],
                rc=code,
                result={"stderr": stderr[:4000], "stdout": stdout[:4000]},
            )
        ]

    return RunModuleResult(
        module=fqcn,
        check_mode=check_mode,
        exit_code=code,
        hosts=host_results,
        raw_stdout=stdout,
        raw_stderr=stderr,
        argv=argv,
    )
