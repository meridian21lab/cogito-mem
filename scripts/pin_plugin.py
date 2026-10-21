"""Point the Claude Code plugin at a cogito-mem release that is on PyPI.

    python scripts/pin_plugin.py 0.2.2

The plugin (plugin/) runs the released package, ``uvx cogito-mem==<version>``, so a release
reaches plugin users in two steps: publish to PyPI (tag ``v<version>``), then run this and
merge the commit. It writes the version into plugin.json, the MCP server and every hook, and
plugin/pyproject.toml, then re-locks plugin/uv.lock, which needs the release on PyPI already.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"
PIN = re.compile(r"cogito-mem==[0-9][0-9A-Za-z.+-]*")


def pin(version: str) -> None:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+([.-]?[0-9A-Za-z]+)*", version):
        raise SystemExit(f"not a version: {version!r}")
    manifest = PLUGIN / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text())
    data["version"] = version
    manifest.write_text(PIN.sub(f"cogito-mem=={version}", json.dumps(data, indent=2, ensure_ascii=False) + "\n"))
    hooks = PLUGIN / "hooks" / "hooks.json"
    hooks.write_text(PIN.sub(f"cogito-mem=={version}", hooks.read_text()))
    project = PLUGIN / "pyproject.toml"
    text = re.sub(r'(?m)^version = "[^"]*"$', f'version = "{version}"', project.read_text())
    project.write_text(PIN.sub(f"cogito-mem=={version}", text))
    subprocess.run(["uv", "lock", "--project", str(PLUGIN)], check=True)
    print(f"plugin now runs cogito-mem {version}; commit plugin/ and merge it to main")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    pin(sys.argv[1])
