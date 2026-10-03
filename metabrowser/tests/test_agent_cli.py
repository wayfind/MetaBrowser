import json

from conftest import SITES
from metabrowser import agent, cli


def test_mcp_registration_preserves_other_servers(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"model": "x", "mcp_servers": [{"name": "github", "command": ["gh-mcp"]},
                                                             {"name": "browser", "command": ["old"]}]}))
    path, old, new = agent.plan_mcp_registration(cfg)
    assert new["model"] == "x"
    assert [s["name"] for s in new["mcp_servers"]] == ["github", "browser"]
    assert new["mcp_servers"][1]["command"][-2:] == ["metabrowser", "mcp"]
    backup = agent.write_mcp_registration(path, new)
    assert json.loads(backup.read_text()) == old
    assert agent.plan_mcp_registration(cfg)[1] == agent.plan_mcp_registration(cfg)[2]  # idempotent


def test_agent_config_reads_secrets_only_from_env(tmp_path, monkeypatch):
    from metabrowser.agentcore import AgentConfig

    (tmp_path / "home").mkdir(exist_ok=True)
    (tmp_path / "home" / "config.json").write_text(json.dumps({"agent": {"model": "m1", "api_key": "IGNORED"}}))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")
    monkeypatch.setenv("METABROWSER_API_KEY", "sekret-123")
    cfg = AgentConfig.load()
    assert cfg.model == "m1" and cfg.api_key == "sekret-123"
    assert cfg.base_url == "https://proxy.example/v1/messages"
    assert cfg.public()["api_key"] == "set" and "sekret" not in json.dumps(cfg.public())


def test_permission_response_echoes_identity():
    from metabrowser.agentcore import permission_response

    req = {"request_id": "r1", "policy_generation": 7, "candidate": {"rule_id": "rule-9"}}
    assert permission_response(req, "allow_once") == {"permission": "allow_once", "request_id": "r1",
                                                      "policy_generation": 7}
    assert permission_response(req, "allow_session")["rule_id"] == "rule-9"


def test_bare_command_means_serve(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_serve", lambda a: seen.setdefault("a", a) and 0)
    cli.main([])
    assert seen["a"].cmd == "serve" and not seen["a"].no_agent and not seen["a"].no_panel


def test_cli_tools_and_sites(capsys):
    assert cli.main(["tools", "--json"]) == 0
    tools = json.loads(capsys.readouterr().out)
    layers = {t["layer"] for t in tools}
    assert layers == {"L1", "L2", "L3"}
    assert cli.main(["site", "validate", str(SITES / "example-shop")]) == 0
    assert "2 capabilities" in capsys.readouterr().out
    assert cli.main(["site", "kg-export", "example_shop"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "metabrowser-site"
