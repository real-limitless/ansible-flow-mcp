from __future__ import annotations

import json
from pathlib import Path

import pytest

from ansible_flow_mcp.runner import (
    build_ansible_argv,
    format_module_args,
    parse_json_callback,
    run_module,
)
from ansible_flow_mcp.security import SecurityPolicy, load_policy

FIXTURES = Path(__file__).parent / "fixtures"


def test_format_module_args_json():
    assert format_module_args(None) is None
    assert json.loads(format_module_args({"path": "/tmp", "state": "directory"})) == {
        "path": "/tmp",
        "state": "directory",
    }


def test_build_argv_check_and_local():
    argv = build_ansible_argv(
        module="ansible.builtin.ping",
        hosts="localhost",
        args={"data": "pong"},
        check_mode=True,
    )
    assert argv[:5] == ["ansible", "localhost", "-m", "ansible.builtin.ping", "-i"]
    assert "--check" in argv
    assert "-c" in argv and "local" in argv
    assert "-a" in argv


def test_parse_json_callback_ping():
    raw = (FIXTURES / "ping_json_callback.json").read_text(encoding="utf-8")
    hosts = parse_json_callback(raw)
    assert len(hosts) == 1
    h = hosts[0]
    assert h.host == "localhost"
    assert h.ok is True
    assert h.changed is False
    assert h.result.get("ping") == "pong"


def test_policy_denies_shell():
    pol = load_policy()
    with pytest.raises(ValueError, match="denied"):
        pol.assert_module_allowed("ansible.builtin.shell")


def test_policy_rejects_bad_fqcn():
    pol = SecurityPolicy(collections={"ansible.builtin"}, deny_modules=set())
    with pytest.raises(ValueError, match="Invalid"):
        pol.assert_module_allowed("../evil")


def test_run_module_with_mock_runner():
    fixture = (FIXTURES / "ping_json_callback.json").read_text(encoding="utf-8")

    def fake_run(argv, env, timeout):
        assert argv[0] == "ansible"
        assert "json" in str(env.get("ANSIBLE_STDOUT_CALLBACK", ""))
        assert "--check" in argv
        return 0, fixture, ""

    pol = SecurityPolicy(
        collections={"ansible.builtin"},
        deny_modules={"ansible.builtin.shell"},
    )
    result = run_module(
        "ansible.builtin.ping",
        check_mode=True,
        policy=pol,
        run_fn=fake_run,
    )
    d = result.to_dict()
    assert d["exitCode"] == 0
    assert d["failed"] is False
    assert d["hosts"][0]["result"]["ping"] == "pong"
    assert d["module"] == "ansible.builtin.ping"


def test_run_module_blocks_disallowed_collection():
    pol = SecurityPolicy(collections={"ansible.builtin"}, deny_modules=set())
    with pytest.raises(ValueError, match="allowlist"):
        run_module("community.general.modprobe", policy=pol, run_fn=lambda *a, **k: (0, "", ""))


def test_build_playbook_argv():
    from ansible_flow_mcp.runner import build_playbook_argv

    argv = build_playbook_argv(
        playbook="/tmp/site.yml",
        inventory="/tmp/inv",
        check_mode=True,
        become=True,
        extra_vars_file="/tmp/vars.json",
        limit="web",
        tags="deploy",
    )
    assert argv[0] == "ansible-playbook"
    assert "--check" in argv
    assert "-e" in argv
    assert "@/tmp/vars.json" in argv


def test_assert_playbook_path_rejects_passwd():
    from ansible_flow_mcp.runner import assert_playbook_path

    with pytest.raises(ValueError):
        assert_playbook_path("/etc/passwd")


def test_run_playbook_mocked(tmp_path):
    from ansible_flow_mcp.runner import run_playbook

    pb = tmp_path / "site.yml"
    pb.write_text("---\n- hosts: localhost\n  tasks: []\n", encoding="utf-8")
    fixture = (FIXTURES / "ping_json_callback.json").read_text(encoding="utf-8")

    def fake_run(argv, env, timeout):
        assert argv[0] == "ansible-playbook"
        assert str(pb) in argv
        assert "--check" in argv
        return 0, fixture, ""

    result = run_playbook(str(pb), check_mode=True, run_fn=fake_run)
    d = result.to_dict()
    assert d["kind"] == "playbook"
    assert d["failed"] is False
    assert d["hosts"][0]["result"]["ping"] == "pong"
