"""Decide whether the hub test autojoin loop can stop.

The shell issues join tokens. This module reads hub state once per pass and
seeds the lab group. It does not print tokens.
"""

from __future__ import annotations

import os
import re
import sys

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def spoke_names(raw: str) -> list[str]:
    names: list[str] = []
    for part in raw.split():
        if _NAME.fullmatch(part) and part not in names:
            names.append(part)
    return names


def plan(
    spokes: set[str],
    groups: dict[str, set[str]],
    names: list[str],
    group: str,
) -> tuple[list[str], bool]:
    """Return spokes still missing, and whether the lab group already matches.

    An empty name list is not ready: there is nothing to enroll.
    An empty group name means membership is not required.
    """
    missing = [name for name in names if name not in spokes]
    if missing or not names:
        return missing, False
    if not group:
        return [], True
    return [], groups.get(group) == set(names)


def _status_view(status: dict) -> tuple[set[str], dict[str, set[str]]]:
    spokes = {str(name) for name in (status.get("spokes") or [])}
    groups: dict[str, set[str]] = {}
    for item in status.get("groups") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        groups[name] = {str(host) for host in (item.get("hosts") or [])}
    return spokes, groups


def reconcile(status: dict, names: list[str], group: str) -> tuple[list[str], bool]:
    spokes, groups = _status_view(status)
    return plan(spokes, groups, names, group)


def main() -> int:
    from ansible_flow_mcp.hub.enroll import create_group_op, hub_status, set_group_members_op

    names = spoke_names(os.environ.get("ANSIBLE_FLOW_TEST_SPOKES") or "")
    group = (os.environ.get("ANSIBLE_FLOW_TEST_GROUP") or "").strip()
    status = hub_status()
    missing, ready = reconcile(status, names, group)
    if missing or not names:
        for name in missing:
            sys.stdout.write(name + "\n")
        return 2
    if ready:
        return 0
    if group not in _status_view(status)[1]:
        create_group_op(group)
    set_group_members_op(group, names)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(f"hub autojoin: {exc}\n")
        raise SystemExit(2) from exc
