"""Request validation for the two operations (requirements §3).

Requests have static keys: an unknown key is an error, an optional key may be left
out or set to null, and the defaults below fill it in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import timeutil
from .errors import invalid

NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
KINDS = ("message", "piece", "digest", "statement")

DEFAULT_NAMESPACE = "default"
DEFAULT_THREAD = "default"
DEFAULT_TOP_K = 10
MAX_TOP_K = 100
DEFAULT_MAX_TOKENS = 300
MAX_MAX_TOKENS = 100_000
MAX_ITEMS = 1000
MAX_TEXT_CHARS = 4_000_000

_APPEND_KEYS = {"op", "namespace", "import", "items"}
_ITEM_KEYS = {"thread_id", "author", "valid_at", "title", "text", "client_ref", "retracts"}
_QUERY_KEYS = {"op", "namespace", "text", "context", "filter", "as_of", "top_k", "max_tokens"}
_FILTER_KEYS = {"thread_id", "author", "kind", "valid_after", "valid_before", "include_retracted"}


@dataclass
class ItemIn:
    author: str
    text: str
    thread_id: str = DEFAULT_THREAD
    valid_at: int | None = None
    title: str | None = None
    client_ref: str | None = None
    retracts: list[str] = field(default_factory=list)


@dataclass
class AppendIn:
    namespace: str
    import_: bool
    items: list[ItemIn]


@dataclass
class FilterIn:
    thread_id: str | None = None
    author: str | None = None
    kind: list[str] | None = None
    valid_after: int | None = None
    valid_before: int | None = None
    include_retracted: bool = False


@dataclass
class QueryIn:
    namespace: str
    text: str
    context: str | None
    filter: FilterIn
    as_of: int | None
    top_k: int
    max_tokens: int


def _check_keys(obj: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise invalid(f"unknown key{'s' if len(unknown) > 1 else ''} in {where}: {', '.join(unknown)}")


def _opt_str(obj: dict, key: str, where: str, *, non_empty: bool = True) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid(f"{where}{key} must be a string")
    if non_empty and not value.strip():
        raise invalid(f"{where}{key} must not be empty")
    return value


def _opt_time(obj: dict, key: str, where: str) -> int | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid(f"{where}{key} must be an RFC 3339 string")
    try:
        return timeutil.parse(value)
    except ValueError as exc:
        raise invalid(f"{where}{key}: {exc}") from None


def _opt_int(obj: dict, key: str, default: int, lo: int, hi: int) -> int:
    value = obj.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(f"{key} must be an integer")
    if not lo <= value <= hi:
        raise invalid(f"{key} must be between {lo} and {hi}, got {value}")
    return value


def _namespace(body: dict) -> str:
    ns = body.get("namespace")
    if ns is None:
        return DEFAULT_NAMESPACE
    if not isinstance(ns, str) or not NAMESPACE_RE.match(ns):
        raise invalid(
            "namespace must be 1-64 characters of letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    return ns


def parse_append(body: dict) -> AppendIn:
    _check_keys(body, _APPEND_KEYS, "the append request")
    namespace = _namespace(body)
    import_ = body.get("import")
    if import_ is None:
        import_ = False
    if not isinstance(import_, bool):
        raise invalid("import must be true or false")
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise invalid("items must be a non-empty list")
    if len(raw_items) > MAX_ITEMS:
        raise invalid(f"at most {MAX_ITEMS} items per request, got {len(raw_items)}")
    items = []
    last_valid = None
    for i, raw in enumerate(raw_items):
        where = f"items[{i}]."
        if not isinstance(raw, dict):
            raise invalid(f"items[{i}] must be an object")
        _check_keys(raw, _ITEM_KEYS, f"items[{i}]")
        author = _opt_str(raw, "author", where)
        if author is None:
            raise invalid(f"{where}author is required")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise invalid(f"{where}text is required and must be a non-empty string")
        if len(text) > MAX_TEXT_CHARS:
            raise invalid(f"{where}text is longer than {MAX_TEXT_CHARS} characters")
        thread_id = _opt_str(raw, "thread_id", where) or DEFAULT_THREAD
        valid_at = _opt_time(raw, "valid_at", where)
        title = _opt_str(raw, "title", where, non_empty=False)
        client_ref = _opt_str(raw, "client_ref", where)
        retracts = raw.get("retracts")
        if retracts is None:
            retracts = []
        if not isinstance(retracts, list) or not all(isinstance(r, str) and r for r in retracts):
            raise invalid(f"{where}retracts must be a list of item ids")
        if import_:
            if valid_at is None:
                raise invalid(f"{where}valid_at is required when import is true")
            if last_valid is not None and valid_at < last_valid:
                raise invalid(f"{where}valid_at must not decrease when import is true")
            last_valid = valid_at
        items.append(
            ItemIn(
                author=author,
                text=text,
                thread_id=thread_id,
                valid_at=valid_at,
                title=title or None,
                client_ref=client_ref,
                retracts=list(dict.fromkeys(retracts)),
            )
        )
    return AppendIn(namespace=namespace, import_=import_, items=items)


def parse_query(body: dict) -> QueryIn:
    _check_keys(body, _QUERY_KEYS, "the query request")
    namespace = _namespace(body)
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise invalid("text is required and must be a non-empty string")
    if len(text) > MAX_TEXT_CHARS:
        raise invalid(f"text is longer than {MAX_TEXT_CHARS} characters")
    context = _opt_str(body, "context", "", non_empty=False) or None
    raw_filter = body.get("filter")
    if raw_filter is None:
        raw_filter = {}
    if not isinstance(raw_filter, dict):
        raise invalid("filter must be an object")
    _check_keys(raw_filter, _FILTER_KEYS, "filter")
    kind = raw_filter.get("kind")
    if kind is not None:
        if isinstance(kind, str):
            raise invalid("filter.kind must be a list of kinds, e.g. [\"message\"]")
        if not isinstance(kind, list) or not all(isinstance(k, str) for k in kind):
            raise invalid("filter.kind must be a list of kinds")
        bad = sorted(set(kind) - set(KINDS))
        if bad:
            raise invalid(f"unknown kind {bad[0]!r}; kinds are {', '.join(KINDS)}")
    include_retracted = raw_filter.get("include_retracted")
    if include_retracted is None:
        include_retracted = False
    if not isinstance(include_retracted, bool):
        raise invalid("filter.include_retracted must be true or false")
    flt = FilterIn(
        thread_id=_opt_str(raw_filter, "thread_id", "filter."),
        author=_opt_str(raw_filter, "author", "filter."),
        kind=kind,
        valid_after=_opt_time(raw_filter, "valid_after", "filter."),
        valid_before=_opt_time(raw_filter, "valid_before", "filter."),
        include_retracted=include_retracted,
    )
    return QueryIn(
        namespace=namespace,
        text=text,
        context=context,
        filter=flt,
        as_of=_opt_time(body, "as_of", ""),
        top_k=_opt_int(body, "top_k", DEFAULT_TOP_K, 1, MAX_TOP_K),
        max_tokens=_opt_int(body, "max_tokens", DEFAULT_MAX_TOKENS, 1, MAX_MAX_TOKENS),
    )
