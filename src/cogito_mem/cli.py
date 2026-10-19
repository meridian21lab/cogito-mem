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


def _root(args: argparse.Namespace) -> Path:
    from .client import default_root

    return Path(args.root).expanduser() if getattr(args, "root", None) else default_root()


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
        config=Config(search=args.search, doc_context=args.doc_context),
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

    threading.Thread(target=memory.open_all, name="cogito-mem-warm-up", daemon=True).start()

    def stop(*_: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
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


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import McpServer

    if args.in_process:
        from .memory import Memory

        memory = Memory(_root(args), embedder=args.embedder)
        handle = memory.handle
    else:
        handle = _client(args).handle
    McpServer(handle, namespace=args.namespace).run()
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    from .install import install

    return install(
        args.client or None, _root(args), download=not args.no_download, start=not args.no_start, url=args.url
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
    root = _root(args)
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


def cmd_import(args: argparse.Namespace) -> int:
    from .capture.exports import import_export

    _print(import_export(_client(args), args.kind, Path(args.path).expanduser(), args.namespace))
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
    _print(_client(args).append([{k: v for k, v in item.items() if v is not None}], namespace=args.namespace))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    resp = _client(args).query(args.text, namespace=args.namespace, top_k=args.top_k, max_tokens=args.max_tokens)
    if args.json:
        _print(resp)
        return 0
    for item in resp["items"]:
        print(f"[{item['score']:.3f}] {item['valid_at']} {item['author']} ({item['thread_id']})")
        print("  " + item["text"].replace("\n", "\n  "))
    print(f"-- {len(resp['items'])} items, {resp['tokens']} tokens, {resp['took_ms']} ms")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    info = _client(args).status()
    if info is None:
        print("cogito-mem is not running (it starts on the first request)")
        return 1
    _print(info)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    stopped = _client(args).stop_server()
    print("stopped" if stopped else "cogito-mem was not running")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    if args.eval_args[:1] == ["locomo"]:
        from .evals import locomo

        return locomo.main(args.eval_args[1:])
    from .evals import longmemeval

    return longmemeval.main(args.eval_args)


def cmd_bench(args: argparse.Namespace) -> int:
    from .evals import speed

    return speed.main(args.bench_args)


# --------------------------------------------------------------------------- parser


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
    sp.add_argument("--doc-context", default="own", choices=["own", "previous"])
    sp.add_argument("--reranker", help="reranker GGUF path or llama-server URL (stage-0 arm R)")

    sp = add("mcp", cmd_mcp, "run the MCP server on stdio")
    sp.add_argument("--namespace", default="default")
    sp.add_argument("--in-process", action="store_true", help="hold the memory in this process instead of the service")
    sp.add_argument("--embedder", default="auto", choices=["auto", "hash", "none"])
    sp.add_argument("--url", help=argparse.SUPPRESS)

    sp = add("install", cmd_install, "connect the memory to chat clients in one step (all found, or the ones named)")
    sp.add_argument("client", nargs="*", help="claude-code, codex or claude-desktop (default: every one installed)")
    sp.add_argument("--url", help="use the service at this URL (e.g. the Docker image) instead of a local one")
    sp.add_argument("--no-download", action="store_true", help="do not download llama.cpp or the model")
    sp.add_argument("--no-start", action="store_true", help="do not start the service")
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
    sp.add_argument("--namespace", default="default")
    sp.add_argument("--all", action="store_true", help="backfill every past session as history")
    sp.add_argument("--wait", action="store_true", help="do the work now instead of in the background")
    sp.add_argument("--url", help=argparse.SUPPRESS)

    sp = add("import", cmd_import, "load past chats from a claude.ai or ChatGPT data export")
    sp.add_argument("kind", choices=["claude", "chatgpt"])
    sp.add_argument("path", help="the export .zip, its folder, or conversations.json")
    sp.add_argument("--namespace", default="default")
    sp.add_argument("--url", help=argparse.SUPPRESS)

    sp = add("request", cmd_request, "send a raw JSON request body (argument or stdin)")
    sp.add_argument("body", nargs="?")
    sp.add_argument("--url")

    sp = add("append", cmd_append, "append one item")
    sp.add_argument("text")
    sp.add_argument("--author", default="user")
    sp.add_argument("--title")
    sp.add_argument("--thread")
    sp.add_argument("--namespace", default="default")
    sp.add_argument("--url")

    sp = add("query", cmd_query, "query the memory")
    sp.add_argument("text")
    sp.add_argument("--namespace", default="default")
    sp.add_argument("--top-k", type=int, default=10)
    sp.add_argument("--max-tokens", type=int, default=300)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--url")

    sp = add("status", cmd_status, "show the service, the model and the namespaces")
    sp.add_argument("--url")
    sp = add("stop", cmd_stop, "stop the local service")
    sp.add_argument("--url")

    sp = add("eval", cmd_eval, "quality tests: LongMemEval (`eval run`, `eval compare`) and LoCoMo (`eval locomo`)")
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
    return int(args.func(args) or 0)
