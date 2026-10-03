"""metacodes integration helpers outside the embedded loop.

* build_core(): build the AgentCore bundle from a metacodes checkout and install
  it as a shared library under ~/.metabrowser/agentcore (the embedded agent).
* MCP registration: lets a *standalone* metacodes CLI use this browser through
  the `browser` MCP server (~/.metacodes/config.json `mcp_servers`).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from . import paths

MCP_SERVER_NAME = "browser"


# -- AgentCore build ----------------------------------------------------------------------

def zig_target() -> str:
    arch = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64", "AMD64": "x86_64"}[platform.machine()]
    if sys.platform == "darwin":
        return f"{arch}-macos.13.0"
    if sys.platform.startswith("linux"):
        return f"{arch}-linux-gnu"
    raise RuntimeError("AgentCore shared-library packaging is implemented for macOS and Linux")


def build_core(metacodes_src: Path, *, optimize: str = "ReleaseSafe", log=print) -> Path:
    """zig build agentcore:bundle -> link the static archive into a shared library -> install."""
    src = Path(metacodes_src).expanduser().resolve()
    if not (src / "build.zig").exists() or not (src / "sdk" / "metask" / "agentcore.h").exists():
        raise RuntimeError(f"{src} is not a metacodes checkout")
    zig = shutil.which("zig")
    if not zig:
        raise RuntimeError("zig not found on PATH (metacodes requires Zig 0.16)")
    prefix = Path(tempfile.mkdtemp(prefix="agentcore-"))
    target = zig_target()
    log(f"building AgentCore for {target} ({optimize}) from {src} …")
    subprocess.run([zig, "build", "agentcore:bundle", "--prefix", str(prefix), f"-Dtarget={target}",
                    f"-Doptimize={optimize}", "-Dagentcore-strip=true"], cwd=src, check=True)
    bundle = next((prefix / "agentcore").iterdir())
    manifest = json.loads((bundle / "manifest.json").read_text())
    contract = manifest["contract"]
    from .agentcore.abi import ABI_REVISION, ABI_VERSION

    if (contract["binary_abi_version"], contract["binary_abi_revision"]) != (ABI_VERSION, ABI_REVISION):
        raise RuntimeError(f"bundle ABI {contract['binary_abi_version']}.{contract['binary_abi_revision']} "
                           f"≠ MetaBrowser binding {ABI_VERSION}.{ABI_REVISION}")
    out = paths.ensure(paths.home() / "agentcore")
    paths.ensure(out / "lib")
    paths.ensure(out / "bin")
    static = bundle / "lib" / "libmetask_agentcore.a"
    if sys.platform == "darwin":
        dylib = out / "lib" / "libmetask_agentcore.dylib"
        cmd = ["clang", "-dynamiclib", "-o", str(dylib), f"-Wl,-force_load,{static}",
               "-Wl,-exported_symbol,_metask_agentcore_get_api", "-install_name", "@rpath/libmetask_agentcore.dylib"]
    else:
        dylib = out / "lib" / "libmetask_agentcore.so"
        cmd = ["cc", "-shared", "-o", str(dylib), "-Wl,--whole-archive", str(static), "-Wl,--no-whole-archive",
               "-lpthread", "-ldl", "-lm"]
    subprocess.run(cmd, check=True)
    shutil.copy2(bundle / "bin" / "rg", out / "bin" / "rg")
    shutil.copy2(bundle / "manifest.json", out / "manifest.json")
    shutil.rmtree(prefix, ignore_errors=True)
    log(f"installed {dylib} (AgentCore {manifest['version']}, ABI {ABI_VERSION}.{ABI_REVISION})")
    return dylib


def find_metacodes_src() -> Optional[Path]:
    for cand in (os.environ.get("METACODES_SRC"), Path.home() / "prj" / "metacodes"):
        if cand and (Path(cand) / "sdk" / "metask" / "agentcore.h").exists():
            return Path(cand)
    return None


# -- standalone metacodes CLI via MCP ---------------------------------------------------------------

def mcp_command() -> list[str]:
    return [sys.executable, "-m", "metabrowser", "mcp"]


def plan_mcp_registration(config_path: Optional[Path] = None) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Return (path, old_config, new_config) adding/updating the `browser` MCP server entry."""
    path = config_path or Path.home() / ".metacodes" / "config.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    new = json.loads(json.dumps(old))
    servers = [s for s in new.get("mcp_servers", []) if s.get("name") != MCP_SERVER_NAME]
    servers.append({"name": MCP_SERVER_NAME, "command": mcp_command()})
    new["mcp_servers"] = servers
    return path, old, new


def write_mcp_registration(path: Path, new: dict[str, Any]) -> Optional[Path]:
    backup = None
    if path.exists():
        backup = path.with_suffix(f".json.bak-{int(time.time())}")
        shutil.copy2(path, backup)
    paths.ensure(path.parent)
    path.write_text(json.dumps(new, indent=2, ensure_ascii=False))
    return backup
