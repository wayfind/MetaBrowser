"""Open Chromium engine, with explicit lifetime and no subscription or startup downloads.

Managed macOS binaries come from a reviewed, digest-pinned manifest. Other
platforms use an installed ungoogled-chromium or an explicitly selected binary.
Playwright Chromium is a deliberate test/development engine, never a fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from . import paths

ENGINES = ("ungoogled", "chromium")


def manifest() -> dict:
    return json.loads(Path(__file__).with_name("browser-builds.json").read_text())


def platform_tag() -> str:
    machine = platform.machine().lower()
    machine = {"aarch64": "arm64", "amd64": "x86_64"}.get(machine, machine)
    return f"{platform.system().lower()}-{machine}"


def managed_dir() -> Path:
    return paths.home() / "browsers" / "ungoogled" / manifest()["version"] / platform_tag()


def executable(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if p.suffix == ".app":
        p = p / "Contents" / "MacOS" / "Chromium"
    if not p.is_file() or not os.access(p, os.X_OK):
        raise FileNotFoundError(f"browser executable not found or not executable: {p}")
    return p


def resolve_binary(engine: str = "ungoogled", selected: str | None = None) -> str | None:
    if engine not in ENGINES:
        raise ValueError(f"unsupported browser engine: {engine}")
    selected = selected or os.environ.get("METABROWSER_BROWSER_PATH")
    if selected:
        return str(executable(selected))
    if engine == "chromium":
        return None  # explicitly requested Playwright's installed Chromium
    candidates = [managed_dir() / "Chromium.app", Path.home() / "Applications/Chromium.app",
                  Path("/Applications/Chromium.app")]
    for name in ("ungoogled-chromium", "ungoogled-chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for p in candidates:
        if p.exists():
            return str(executable(p))
    raise FileNotFoundError(
        "ungoogled-chromium is not installed. Run `metabrowser browser install` on macOS, "
        "or install it from your distribution and pass --browser-path /path/to/chromium "
        "(METABROWSER_BROWSER_PATH). For tests only: --engine chromium. "
        "No CloakBrowser or other browser is downloaded as a fallback."
    )


def verify_sha256(file: Path, expected: str) -> None:
    h = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    if h.hexdigest() != expected:
        raise ValueError("browser archive SHA-256 mismatch; refusing installation")


def install_browser(archive: Path | None = None) -> Path:
    spec = manifest()["builds"].get(platform_tag())
    if spec is None:
        raise ValueError("automatic install currently supports macOS arm64/x86_64; "
                         "install ungoogled-chromium for your platform and use --browser-path")
    dest = managed_dir()
    existing = dest / "Chromium.app"
    if archive:
        verify_sha256(archive.expanduser().resolve(), spec["sha256"])
    if existing.exists():
        return executable(existing)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="metabrowser-browser-", dir=dest.parent) as work:
        work = Path(work)
        if archive:
            dmg = archive.expanduser().resolve()
        else:
            dmg = work / "browser.dmg"
            with urllib.request.urlopen(spec["url"], timeout=120) as response, dmg.open("wb") as output:
                shutil.copyfileobj(response, output)
        if not archive:
            verify_sha256(dmg, spec["sha256"])
        mount = work / "mount"
        mount.mkdir()
        subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-plist", "-mountpoint", str(mount), str(dmg)],
                       check=True, capture_output=True)
        try:
            source = mount / "Chromium.app"
            if not source.is_dir():
                raise ValueError("verified browser image contains no Chromium.app")
            stage = work / "stage"
            stage.mkdir()
            # ditto preserves the signed bundle, links and executable modes.
            subprocess.run(["ditto", str(source), str(stage / "Chromium.app")], check=True)
            executable(stage / "Chromium.app")
            (stage / "install.json").write_text(json.dumps({"engine": "ungoogled", "version": manifest()["version"],
                                                           "platform": platform_tag(), **spec}, indent=2))
            stage.rename(dest)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True, capture_output=True)
    return executable(existing)


def chromium_args(args: list[str], extensions: list[str]) -> list[str]:
    # These launch flags reduce obvious automation signals; not a claim to fix
    # Playwright/CDP fingerprinting or to carry CloakBrowser C++ stealth patches.
    forbidden = ("--fingerprint", "--license-key", "--remote-debugging-pipe", "--user-data-dir", "--load-extension",
                 "--disable-extensions-except")
    if any(a.split("=", 1)[0].startswith(forbidden) for a in args):
        raise ValueError("fingerprint/license, profile, CDP pipe and extension flags are not supported as browser-arg")
    result = ["--site-per-process", "--disable-blink-features=AutomationControlled", *args]
    if extensions:
        ext = []
        for p in extensions:
            resolved = Path(p).expanduser().resolve()
            if not (resolved / "manifest.json").is_file() or "," in str(resolved):
                raise ValueError(f"invalid extension directory: {resolved}")
            ext.append(str(resolved))
        joined = ",".join(ext)
        result.extend([f"--disable-extensions-except={joined}", f"--load-extension={joined}"])
    return result


def proxy_options(proxy: str | None) -> dict | None:
    if not proxy:
        return None
    parsed = urlsplit(proxy)
    if parsed.scheme not in ("http", "https", "socks5") or not parsed.hostname or parsed.path not in ("", "/"):
        raise ValueError("proxy must be an http://, https:// or socks5:// URL")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    result = {"server": f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")}
    if parsed.username is not None:
        if parsed.scheme == "socks5":
            raise ValueError("SOCKS5 username/password authentication is not supported by this engine")
        result.update(username=unquote(parsed.username), password=unquote(parsed.password or ""))
    return result


def patch_context(context: Any) -> None:
    from .human import patch_context_async
    from .human.config import resolve_config

    patch_context_async(context, resolve_config("default"))


class Engine:
    """Own exactly one Playwright driver and the persistent context/browser it starts."""
    def __init__(self, options: Any):
        self.options = options
        self.driver = None
        self.instance = None

    async def start(self, *, profile: Path | None = None):
        from playwright.async_api import async_playwright

        o = self.options
        exe = resolve_binary(o.engine, o.browser_path)
        args = chromium_args(o.args, o.extension_paths if profile else [])
        proxy = proxy_options(o.proxy)
        self.driver = await async_playwright().start()
        common = dict(executable_path=exe, headless=o.headless, args=args, proxy=proxy,
                      chromium_sandbox=True, ignore_default_args=["--enable-automation", "--disable-extensions"])
        try:
            if profile:
                self.instance = await self.driver.chromium.launch_persistent_context(
                    str(profile), **common, accept_downloads=True, viewport=None,
                    locale=o.locale, timezone_id=o.timezone,
                )
                if o.humanize:
                    patch_context(self.instance)
            else:
                self.instance = await self.driver.chromium.launch(**common)
            return self.instance
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        try:
            if self.instance:
                await self.instance.close()
        finally:
            self.instance = None
            if self.driver:
                driver, self.driver = self.driver, None
                await driver.stop()


def validate_profile(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
        raise ValueError("profile must be 1–80 letters, digits, underscores or hyphens")
