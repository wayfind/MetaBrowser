import json
import os
import time
from pathlib import Path

import pytest

from metabrowser import cli, engine
from metabrowser.runtime import BrowserRuntime, LaunchOptions


def test_default_engine_does_not_fall_back_or_download(tmp_path, monkeypatch):
    monkeypatch.delenv("METABROWSER_BROWSER_PATH", raising=False)
    monkeypatch.setattr(engine, "managed_dir", lambda: tmp_path / "absent")
    monkeypatch.setattr(engine.Path, "exists", lambda self: False)
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="browser install"):
        engine.resolve_binary()
    assert engine.resolve_binary("chromium") is None
    with pytest.raises(ValueError):
        engine.resolve_binary("cloak")


def test_explicit_selection_never_falls_back(tmp_path, monkeypatch):
    binary = tmp_path / "Chromium.app/Contents/MacOS/Chromium"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("METABROWSER_BROWSER_PATH", str(binary.parents[2]))
    assert engine.resolve_binary() == str(binary)
    with pytest.raises(FileNotFoundError):
        engine.resolve_binary(selected=str(tmp_path / "bad"))


def test_archive_integrity_and_cli_install_result(tmp_path, monkeypatch, capsys):
    import hashlib

    archive = tmp_path / "test.dmg"
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        engine.verify_sha256(archive, "0" * 64)
    engine.verify_sha256(archive, hashlib.sha256(b"tampered").hexdigest())
    # An explicit offline archive is checked even if the managed app already exists.
    installed = tmp_path / "managed"
    (installed / "Chromium.app").mkdir(parents=True)
    monkeypatch.setattr(engine, "platform_tag", lambda: "darwin-arm64")
    monkeypatch.setattr(engine, "managed_dir", lambda: installed)
    monkeypatch.setattr(engine, "manifest", lambda: {
        "version": "test", "builds": {"darwin-arm64": {"sha256": "0" * 64}}})
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        engine.install_browser(archive)
    monkeypatch.setattr(engine, "install_browser", lambda archive: tmp_path / "Chromium")
    assert cli.main(["browser", "install", "--archive", str(archive)]) == 0
    assert json.loads(capsys.readouterr().out)["executable"] == str(tmp_path / "Chromium")


def test_launch_arguments_and_profile_validation(tmp_path):
    ext = tmp_path / "extension"
    ext.mkdir()
    (ext / "manifest.json").write_text("{}")
    args = engine.chromium_args(["--window-size=1200,800"], [str(ext)])
    assert f"--load-extension={ext}" in args
    for flag in ("--fingerprint=2", "--remote-debugging-pipe", "--user-data-dir=/tmp/x"):
        with pytest.raises(ValueError):
            engine.chromium_args([flag], [])
    for profile in ("../outside", "/tmp/x", "", "a/b"):
        with pytest.raises(ValueError):
            engine.validate_profile(profile)
    engine.validate_profile("project-1")
    assert engine.proxy_options("http://a%40b:p%3Ass@localhost:8080") == {
        "server": "http://localhost:8080", "username": "a@b", "password": "p:ss"}
    with pytest.raises(ValueError):
        engine.proxy_options("socks5://user:pass@localhost:1080")


def test_browser_cli_options_reach_runtime(monkeypatch):
    options = []
    monkeypatch.setattr(cli, "cmd_serve", lambda a: options.append(cli._launch_options(a)))
    assert cli.main(["--browser-path", "/tmp/my-chromium", "--profile", "work", "--no-humanize"]) == 0
    assert options[0].engine == "ungoogled"
    assert options[0].browser_path == "/tmp/my-chromium"
    assert not options[0].humanize


async def test_persistent_engine_preserves_login_and_releases_driver(tmp_path):
    options = LaunchOptions(engine="chromium", browser_path=os.environ.get("METABROWSER_TEST_CHROMIUM"),
                            headless=True, profile="persist")
    runtime = BrowserRuntime(options)
    await runtime.start()
    owner = runtime._engine
    try:
        assert owner.driver is not None
        await runtime.context.add_cookies([{"name": "login", "value": "retained", "domain": "example.test",
                                           "path": "/", "expires": time.time() + 86400}])
        page = runtime.context.pages[0]
        assert await page.evaluate("navigator.webdriver") is False
        await page.goto("data:text/html,<h1>Persistent engine</h1><input id='name'>")
        await page.fill("#name", "中文 hello")
        assert await page.input_value("#name") == "中文 hello"
    finally:
        await runtime.stop()
    assert owner.driver is None and owner.instance is None
    await runtime.start()
    try:
        assert any(c["name"] == "login" and c["value"] == "retained" for c in await runtime.context.cookies())
    finally:
        await runtime.stop()


async def test_failed_browser_launch_stops_playwright_driver(tmp_path, monkeypatch):
    binary = tmp_path / "not-a-browser"
    binary.write_text("#!/bin/sh\nexit 7\n")
    binary.chmod(0o755)
    owner = engine.Engine(LaunchOptions(browser_path=str(binary), headless=True))
    with pytest.raises(Exception):
        await owner.start(profile=tmp_path / "profile")
    assert owner.driver is None and owner.instance is None
