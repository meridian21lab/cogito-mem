"""The ``cogito-mem`` command."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from . import __version__
from .api import DEFAULT_MAX_TOKENS


def _root(args: argparse.Namespace) -> Path:
    from .client import default_root

    return Path(args.root).expanduser() if getattr(args, "root", None) else default_root()


def _namespace(args: argparse.Namespace) -> str:
    """``--namespace``, or the memory's name (``names.default_namespace``)."""
    if not getattr(args, "namespace", None):
        from .names import default_namespace

        args.namespace = default_namespace(_root(args))
    return args.namespace


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _client(args: argparse.Namespace):
    from .client import Client

    return Client(url=getattr(args, "url", None), root=_root(args))


# --------------------------------------------------------------------------- commands


def cmd_serve(args: argparse.Namespace) -> int:
    from .memory import Config, Memory
    from .server import MemoryServer, default_port

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    reranker = None
    rerank_server = None
    root = _root(args)
    if args.reranker or os.environ.get("COGITO_MEM_RERANKER"):
        from .runtime import start_reranker

        reranker, rerank_server = start_reranker(args.reranker or os.environ["COGITO_MEM_RERANKER"], root)
    memory = Memory(
        root,
        embedder=args.embedder,
        config=Config(search=args.search, doc_context=args.doc_context, doc_author=args.doc_author),
        reranker=reranker,
    )
    port = args.port if args.port is not None else default_port()
    try:
        server = MemoryServer(memory, host=args.host, port=port, idle_timeout=args.idle_timeout)
    except OSError as exc:
        from .client import Client

        if Client(url=f"http://{args.host}:{port}", root=root, autostart=False).status() is not None:
            print(f"cogito-mem is already running at http://{args.host}:{port}", file=sys.stderr)
            memory.close()
            return 0
        print(f"cannot listen on {args.host}:{port}: {exc}", file=sys.stderr)
        memory.close()
        return 1

    _migrate_before_serving(root)
    threading.Thread(target=memory.open_all, name="cogito-mem-warm-up", daemon=True).start()

    def stop(*_: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGUSR1"):  # `kill -USR1 <pid>` prints every thread's stack to the log
        import faulthandler

        faulthandler.register(signal.SIGUSR1, all_threads=True)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, stop)
    logging.info("cogito-mem %s serving %s at %s", __version__, root, server.url)
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    finally:
        memory.close()
        if rerank_server is not None:
            rerank_server.stop()
    return 0


def _migrate_before_serving(root: Path) -> None:
    """Rename ``memory/default`` to the chosen name, now that no other service holds the folder."""
    from .names import InvalidName, chosen_namespace, migrate_default

    try:
        name = chosen_namespace(root)
        if name is not None:
            migrate_default(root, name)
    except (InvalidName, OSError) as exc:
        logging.warning("the memory's name: %s", exc)


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import McpServer
    from .names import InvalidName

    if args.in_process:
        from .memory import Memory

        memory = Memory(_root(args), embedder=args.embedder)
        handle = memory.handle
    else:
        handle = _client(args).handle
    try:
        namespace = _namespace(args)
    except InvalidName as exc:  # answer every tool call with the reason, so the assistant can say it
        namespace, handle = None, _refuse(str(exc))
    McpServer(handle, namespace=namespace).run()
    return 0


def _refuse(message: str):
    from .errors import ApiError

    def handle(body: dict) -> dict:
        raise ApiError("invalid_argument", message)

    return handle


def cmd_install(args: argparse.Namespace) -> int:
    from .install import install

    return install(
        args.client or None,
        _root(args),
        download=not args.no_download,
        start=not args.no_start,
        url=args.url,
        recall=not args.no_recall,
        name=args.name,
    )


def cmd_setup(args: argparse.Namespace) -> int:
    from .install import setup

    return setup(_root(args), model_only=args.model_only)


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import doctor

    return doctor(_root(args), url=args.url)


def cmd_uninstall(args: argparse.Namespace) -> int:
    from .install import uninstall

    return uninstall(args.client, _root(args))


def _detach(argv: list[str], root: Path) -> None:
    import subprocess

    run = root / "run"
    run.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000008}
    with open(run / "capture.log", "ab") as out:
        subprocess.Popen(
            [sys.executable, "-m", "cogito_mem", *argv],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            **kwargs,
        )


def cmd_capture(args: argparse.Namespace) -> int:
    from .capture import enabled

    if not args.all and not enabled():  # COGITO_MEM_CAPTURE=off pauses the hooks; a backfill you ask for still runs
        return 0
    root = _root(args)
    _namespace(args)
    state = root / "run" / "capture"
    if args.source == "claude-code":
        from .capture import claude_code

        if args.all:
            _print(claude_code.capture_all(_client(args), state, args.namespace))
            return 0
        if args.transcript is None:  # called as a hook: read its JSON, then work in the background
            try:
                hook = json.load(sys.stdin)
            except ValueError:
                return 0
            transcript = hook.get("transcript_path")
            if not transcript:
                return 0
            argv = ["capture", "claude-code", "--transcript", transcript, "--namespace", args.namespace]
            if hook.get("session_id"):
                argv += ["--session", hook["session_id"]]
            if args.wait:
                args.transcript, args.session = transcript, hook.get("session_id")
            else:
                _detach(argv + ["--root", str(root)], root)
                return 0
        counts = claude_code.capture_transcript(
            _client(args), Path(args.transcript), state, args.session, args.namespace
        )
        print(json.dumps(counts))
        return 0
    if args.source == "codex":
        from .capture import codex

        if not args.wait and not args.all:
            _detach(["capture", "codex", "--wait", "--namespace", args.namespace, "--root", str(root)], root)
            return 0
        counts = codex.sweep(
            _client(args), state, args.namespace, since_days=None if args.all else 2.0, import_=args.all
        )
        print(json.dumps(counts))
        return 0
    return 2


def cmd_recall(args: argparse.Namespace) -> int:
    from .client import Client
    from .names import InvalidName
    from .recall import TIMEOUT, _log, claude_code_hook

    root = _root(args)
    try:
        _namespace(args)
    except InvalidName as exc:  # recall is a hint: say nothing, and note why
        _log(root / "run" / "recall.log", "recall", exc)
        return 0
    out = claude_code_hook(
        sys.stdin.read,
        lambda: Client(url=args.url, root=root, autostart=False, timeout=TIMEOUT),
        namespace=args.namespace,
        min_score=args.min_score,
        max_tokens=args.max_tokens,
        log=root / "run" / "recall.log",
    )
    if out:
        print(out)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from .capture.exports import import_export

    _print(import_export(_client(args), args.kind, Path(args.path).expanduser(), _namespace(args)))
    return 0


def cmd_request(args: argparse.Namespace) -> int:
    from .errors import ApiError

    body = json.loads(args.body) if args.body else json.load(sys.stdin)
    try:
        _print(_client(args).handle(body))
    except ApiError as err:
        _print(err.body())
        return 1
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    item = {"author": args.author, "text": args.text, "title": args.title, "thread_id": args.thread}
    _print(_client(args).append([{k: v for k, v in item.items() if v is not None}], namespace=_namespace(args)))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    resp = _client(args).query(args.text, namespace=_namespace(args), top_k=args.top_k, max_tokens=args.max_tokens)
    if args.json:
        _print(resp)
        return 0
    for item in resp["items"]:
        print(f"[{item['score']:.3f}] {item['valid_at']} {item['author']} ({item['thread_id']})")
        print("  " + item["text"].replace("\n", "\n  "))
    print(f"-- {len(resp['items'])} items, {resp['tokens']} tokens, {resp['took_ms']} ms")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    name = _namespace(args)
    info = _client(args).status()
    if info is None:
        print(f"cogito-mem is not running (it starts on the first request); memory: {name}")
        return 1
    _print({"memory": name, **info})
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    stopped = _client(args).stop_server()
    print("stopped" if stopped else "cogito-mem was not running")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    if args.eval_args[:1] == ["locomo-qa"]:
        from .evals import locomo_qa

        return locomo_qa.main(args.eval_args[1:])
    if args.eval_args[:1] == ["locomo"]:
        from .evals import locomo

        return locomo.main(args.eval_args[1:])
    if args.eval_args[:1] == ["longmemeval-recall"]:
        from .evals import longmemeval_recall

        return longmemeval_recall.main(args.eval_args[1:])
    from .evals import longmemeval

    return longmemeval.main(args.eval_args)


def cmd_bench(args: argparse.Namespace) -> int:
    from .evals import speed

    return speed.main(args.bench_args)


# --------------------------------------------------------------------------- parser

NAMESPACE_HELP = "the memory to use (default: $COGITO_MEM_NAMESPACE, the saved name, or <username>-hollow)"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cogito-mem", description="A fast, simple, local memory for agents.")
    p.add_argument("--version", action="version", version=f"cogito-mem {__version__}")
    p.add_argument("--root", help="memory folder (default: $COGITO_MEM_HOME or ~/.cogito-mem)")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, func, help: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, description=help)
        sp.add_argument("--root", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        sp.set_defaults(func=func)
        return sp

    sp = add("serve", cmd_serve, "run the local service (POST /v1/memory)")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=None, help="default: $COGITO_MEM_PORT or 7327")
    sp.add_argument("--idle-timeout", type=float, default=3600.0, help="stop after this many idle seconds (0: never)")
    sp.add_argument("--embedder", default="auto", choices=["auto", "hash", "none"])
    sp.add_argument("--search", default="hybrid", choices=["hybrid", "vector", "keyword"])
    sp.add_argument("--doc-context", default="previous", choices=["own", "previous"])
    sp.add_argument("--doc-author", action=argparse.BooleanOptionalAction, default=True,
                    help="put each author's name before their text for search (default: on)")  # fmt: skip
    sp.add_argument("--reranker", help="reranker GGUF path or llama-server URL (stage-0 arm R)")

    sp = add("mcp", cmd_mcp, "run the MCP server on stdio")
    sp.add_argument("--namespace", help=NAMESPACE_HELP)
    sp.add_argument("--in-process", action="store_true", help="hold the memory in this process instead of the service")
    sp.add_argument("--embedder", default="auto", choices=["auto", "hash", "none"])
    sp.add_argument("--url", help=argparse.SUPPRESS)

    sp = add("install", cmd_install, "connect the memory to chat clients in one step (all found, or the ones named)")
    sp.add_argument("client", nargs="*", help="claude-code, codex or claude-desktop (default: every one installed)")
    sp.add_argument("--url", help="use the service at this URL (e.g. the Docker image) instead of a local one")
    sp.add_argument("--no-download", action="store_true", help="do not download llama.cpp or the model")
    sp.add_argument("--no-start", action="store_true", help="do not start the service")
    sp.add_argument("--name", help="the memory's name (default: the saved name, or <username>-hollow)")
    sp.add_argument("--no-recall", action="store_true",
                    help="Claude Code: do not add relevant memory to each prompt (run install again to change)")  # fmt: skip
    sp = add("uninstall", cmd_uninstall, "disconnect the memory from a chat client (the memory is kept)")
    sp.add_argument("client", choices=["claude-code", "codex", "claude-desktop"])
    sp = add("setup", cmd_setup, "download llama.cpp and the embedding model, without touching any client")
    sp.add_argument("--model-only", action="store_true")
    sp = add("doctor", cmd_doctor, "check the install and say how to fix what is missing")
    sp.add_argument("--url")

    sp = add("capture", cmd_capture, "append new chat messages (used by the client hooks)")
    sp.add_argument("source", choices=["claude-code", "codex"])
    sp.add_argument("payload", nargs="?", help=argparse.SUPPRESS)  # Codex notify passes a JSON argument
    sp.add_argument("--transcript")
    sp.add_argument("--session")
    sp.add_argument("--namespace", help=NAMESPACE_HELP)
    sp.add_argument("--all", action="store_true", help="backfill every past session as history")
    sp.add_argument("--wait", action="store_true", help="do the work now instead of in the background")
    sp.add_argument("--url", help=argparse.SUPPRESS)

    sp = add("recall", cmd_recall, "add what the memory knows to a Claude Code prompt or new session (used by the hooks)")
    sp.add_argument("source", choices=["claude-code"])
    sp.add_argument("--namespace", help=NAMESPACE_HELP)
    sp.add_argument("--min-score", type=float, help="leave out items that score lower (default: 0.6, or $COGITO_MEM_RECALL_MIN_SCORE)")
    sp.add_argument("--max-tokens", type=int, default=300)
    sp.add_argument("--url", help=argparse.SUPPRESS)

    sp = add("import", cmd_import, "load past chats from a claude.ai or ChatGPT data export")
    sp.add_argument("kind", choices=["claude", "chatgpt"])
    sp.add_argument("path", help="the export .zip, its folder, or conversations.json")
    sp.add_argument("--namespace", help=NAMESPACE_HELP)
    sp.add_argument("--url", help=argparse.SUPPRESS)

    sp = add("request", cmd_request, "send a raw JSON request body (argument or stdin)")
    sp.add_argument("body", nargs="?")
    sp.add_argument("--url")

    sp = add("append", cmd_append, "append one item")
    sp.add_argument("text")
    sp.add_argument("--author", default="user")
    sp.add_argument("--title")
    sp.add_argument("--thread")
    sp.add_argument("--namespace", help=NAMESPACE_HELP)
    sp.add_argument("--url")

    sp = add("query", cmd_query, "query the memory")
    sp.add_argument("text")
    sp.add_argument("--namespace", help=NAMESPACE_HELP)
    sp.add_argument("--top-k", type=int, default=10)
    sp.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--url")

    sp = add("status", cmd_status, "show the memory's name, the service, the model and the namespaces")
    sp.add_argument("--url")
    sp = add("stop", cmd_stop, "stop the local service")
    sp.add_argument("--url")

    sp = add("eval", cmd_eval, "quality tests: LongMemEval (`eval run`, `eval compare`, `eval longmemeval-recall`), "
             "LoCoMo (`eval locomo`, `eval locomo-qa`)")
    sp.add_argument("eval_args", nargs=argparse.REMAINDER)
    sp = add("bench", cmd_bench, "speed test (requirements §6); see `cogito-mem bench -h`")
    sp.add_argument("bench_args", nargs=argparse.REMAINDER)
    return p


def main(argv: list[str] | None = None) -> int:
    # The one large product per query is memory-bound, and idle BLAS threads spin on the cores
    # llama-server needs for the next query's embedding: keep BLAS to one thread (not OpenMP,
    # which llama.cpp uses). Takes effect because numpy is imported later, by the command.
    for var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(var, "1")
    args = build_parser().parse_args(argv)
    from .names import InvalidName, log

    if args.func is not cmd_serve and not log.handlers:  # e.g. "renamed the memory ..." on stderr
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("cogito-mem: %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    try:
        return int(args.func(args) or 0)
    except InvalidName as exc:
        print(f"cogito-mem: {exc}", file=sys.stderr)
        return 1
