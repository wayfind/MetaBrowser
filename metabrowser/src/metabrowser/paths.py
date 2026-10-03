"""Filesystem layout under ~/.metabrowser (override with METABROWSER_HOME)."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("METABROWSER_HOME", Path.home() / ".metabrowser")).expanduser()


def profiles_dir() -> Path:
    return home() / "profiles"


def traces_dir() -> Path:
    return home() / "traces"


def artifacts_dir() -> Path:
    return home() / "artifacts"


def sites_dir() -> Path:
    return home() / "sites"


def daemon_file() -> Path:
    """Port + bearer token of the running daemon (mode 0600)."""
    return home() / "daemon.json"


def workspace_dir() -> Path:
    """The embedded agent's workspace root (outputs live inside it)."""
    return Path(os.environ.get("METABROWSER_WORKSPACE", Path.home() / "MetaBrowser")).expanduser()


def outputs_dir() -> Path:
    """User-visible output folder (reports, downloads). Agents may write here by default."""
    return Path(os.environ.get("METABROWSER_OUTPUTS", Path.home() / "MetaBrowser" / "outputs")).expanduser()


def package_root() -> Path:
    """Directory holding the bundled extension/ and sites/ (source checkout or wheel)."""
    here = Path(__file__).resolve().parent
    if (here / "_extension").is_dir():
        return here
    return here.parent.parent  # metabrowser/ in a source checkout


def bundled_extension_dir() -> Path:
    root = package_root()
    return root / "_extension" if (root / "_extension").is_dir() else root / "extension"


def bundled_sites_dir() -> Path:
    root = package_root()
    return root / "_sites" if (root / "_sites").is_dir() else root / "sites"


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
