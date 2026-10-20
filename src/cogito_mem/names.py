"""The memory's name: ``<username>-hollow``, unless you choose another (requirements §15).

Cogi, the squirrel, keeps its nuts in a hollow. Every client (the CLI, the MCP server,
the hooks, ``install``) asks ``default_namespace()`` and sends the answer with each
request. The name comes from, in order:

1. ``$COGITO_MEM_NAMESPACE``, when it is set and not empty;
2. ``config.json`` in the memory folder (``{"namespace": "ksirg-hollow"}``);
3. ``<username>-hollow``.

The name in use is saved to ``config.json``, so a client without the variable agrees
with one that has it. The first time a name is saved, the memory from before names
(``memory/default``) is renamed to it, so nothing is lost.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import re
from pathlib import Path

from .api import NAMESPACE_RE

log = logging.getLogger("cogito_mem.names")

ENV = "COGITO_MEM_NAMESPACE"
CONFIG = "config.json"
LEGACY = "default"  # the one name every client used before names
RULE = "1-64 letters, digits, '.', '_' or '-', starting with a letter or digit"


class InvalidName(ValueError):
    """A name from the environment, the config file or ``--name`` breaks the rule."""


def check(name: object, where: str) -> str:
    if not isinstance(name, str) or not NAMESPACE_RE.match(name):
        raise InvalidName(f"{where} {name!r} is not a valid memory name: use {RULE}")
    return name


def hollow(user: str | None = None) -> str:
    """``<username>-hollow``, the username cut down to what a name may hold."""
    if user is None:
        try:
            user = getpass.getuser()
        except Exception:  # no USER, LOGNAME or passwd entry (e.g. some containers)
            user = ""
    stem = re.sub(r"[^a-z0-9._-]+", "-", user.lower()).strip("._-")[:57].rstrip("._-")
    return f"{stem}-hollow" if stem else "my-hollow"


def _env_name() -> str | None:
    value = os.environ.get(ENV, "").strip()
    if not value or value.startswith("${"):  # empty, or a placeholder a client did not fill in
        return None
    return check(value, f"${ENV}")


def saved_namespace(root: Path) -> str | None:
    """The name in ``config.json``, or None when there is none yet."""
    path = root / CONFIG
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise InvalidName(f"cannot read {path} ({exc}); fix it or delete it") from None
    name = data.get("namespace") if isinstance(data, dict) else None
    return None if name is None else check(name, f"the namespace in {path}")


def _save(root: Path, name: str) -> None:
    path = root / CONFIG
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    data["namespace"] = name
    root.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(CONFIG + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def default_namespace(root: Path | None = None) -> str:
    """The memory every client uses unless told otherwise."""
    from .client import default_root

    return _settle(root or default_root(), _env_name())


def set_namespace(root: Path, name: str) -> str:
    """Choose the memory's name (``cogito-mem install --name``)."""
    return _settle(root, check(name, "--name"))


def chosen_namespace(root: Path) -> str | None:
    """The name from the environment or ``config.json``, or None: for the service, which never guesses."""
    wanted = _env_name()
    if wanted is None and saved_namespace(root) is None:
        return None
    return _settle(root, wanted, stop_service=False)


def _settle(root: Path, wanted: str | None, stop_service: bool = True) -> str:
    saved = saved_namespace(root)
    if saved is not None and wanted in (None, saved):
        return saved
    from .client import _file_lock

    try:
        with _file_lock(root / "run" / "namespace.lock"):
            saved = saved_namespace(root)
            name = wanted or saved or hollow()
            if saved is None:  # the first name: bring the memory from before names along
                _migrate(root, name, stop_service)
            if name != saved:
                _save(root, name)  # after the rename, so no client uses the name before it
    except OSError as exc:  # a read-only folder: use the name without saving it
        log.warning("could not save the memory's name in %s: %s", root / CONFIG, exc)
        name = wanted or saved or hollow()
    return name


def migrate_default(root: Path, name: str) -> None:
    """Rename ``memory/default`` to ``memory/<name>`` (the service, before it opens any memory)."""
    from .client import _file_lock

    with _file_lock(root / "run" / "namespace.lock"):
        _migrate(root, name, stop_service=False)


def _migrate(root: Path, name: str, stop_service: bool) -> None:
    if name.lower() == LEGACY:
        return
    old, new = root / "memory" / LEGACY, root / "memory" / name
    if not (old / "log.sqlite3").exists():
        return
    if new.exists():
        log.warning("both %s and %s exist; both are kept, and the clients use %s", old, new, name)
        return
    if stop_service:
        _stop_service(root)
    try:
        old.rename(new)
    except OSError as exc:
        log.warning("could not rename %s to %s (%s); the clients now use %s", old, new, exc, name)
        return
    log.info("renamed the memory %s to %s", old, new)


def _stop_service(root: Path) -> None:
    """Stop a service that holds this memory folder open, so the rename is safe; any request restarts it."""
    from .client import Client

    client = Client(root=root, autostart=False)
    info = client.status()
    if not info or not info.get("root") or info.get("pid") == os.getpid():
        return
    try:
        same = Path(info["root"]).resolve() == root.resolve()
    except OSError:
        same = False
    if same:
        log.info("stopping the service (pid %s) to rename the memory", info.get("pid"))
        client.stop_server()
