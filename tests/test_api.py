"""The API contract of requirements §3: static keys, defaults, errors, time, retraction, filters, budget."""

from __future__ import annotations

import uuid

import pytest
from conftest import append, query

from cogito_mem import ApiError, timeutil

QUERY_KEYS = {"items", "as_of", "tokens", "took_ms"}
ITEM_KEYS = {"id", "kind", "text", "score", "author", "thread_id", "valid_at", "created_at", "expired_at", "source"}
SOURCE_KEYS = {"id", "title", "start", "end"}


def test_append_response_shape(mem):
    resp = append(mem, {"author": "planning-agent", "text": "Integration costs are 40 % above plan."})
    assert set(resp) == {"items", "took_ms"}
    (item,) = resp["items"]
    assert set(item) == {"id", "created_at", "status", "pieces"}
    assert item["status"] == "added"
    assert item["pieces"] == 1
    assert uuid.UUID(item["id"]).version == 7
    timeutil.parse(item["created_at"])


def test_query_response_has_every_key_every_time(mem):
    append(
        mem,
        {
            "thread_id": "merger-x",
            "author": "planning-agent",
            "valid_at": "2026-10-14T16:00:00Z",
            "title": "Jana's report on merger X",
            "text": "Integration costs are 40 % above plan.",
        },
        {"author": "user", "text": "Picnic on Saturday."},
    )
    assert mem.flush(10)  # vectors are made in the background; wait so both lists take part
    resp = query(mem, "What did Jana's report say about costs?")
    assert set(resp) == QUERY_KEYS
    assert resp["items"]
    for item in resp["items"]:
        assert set(item) == ITEM_KEYS
        assert set(item["source"]) == SOURCE_KEYS
        assert 0.0 <= item["score"] <= 1.0
        assert item["expired_at"] is None
    top = resp["items"][0]
    assert top["text"] == "Integration costs are 40 % above plan."
    assert top["kind"] == "message"
    assert top["thread_id"] == "merger-x"
    assert top["author"] == "planning-agent"
    assert top["valid_at"] == "2026-10-14T16:00:00.000Z"
    assert top["source"] == {"id": top["id"], "title": "Jana's report on merger X", "start": 0, "end": 38}
    other = [i for i in resp["items"] if i["author"] == "user"][0]
    assert other["source"]["title"] is None and other["thread_id"] == "default"


def test_empty_memory_returns_static_shape(mem):
    resp = query(mem, "anything")
    assert resp["items"] == [] and resp["tokens"] == 0 and set(resp) == QUERY_KEYS


def test_scores_are_in_order(mem):
    for i in range(20):
        append(mem, {"author": "user", "text": f"note {i} about apples and pears number {i}"})
    items = query(mem, "apples pears", top_k=20, max_tokens=10_000)["items"]
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    assert len(items) == 20


@pytest.mark.parametrize(
    "body, fragment",
    [
        ({"op": "nope"}, "op must be"),
        ({"op": "append", "items": []}, "items must be a non-empty list"),
        ({"op": "append", "items": [{"text": "x"}]}, "author is required"),
        ({"op": "append", "items": [{"author": "a", "text": "  "}]}, "text is required"),
        ({"op": "append", "items": [{"author": "a", "text": "x", "colour": 1}]}, "unknown key"),
        ({"op": "append", "items": [{"author": "a", "text": "x", "valid_at": "yesterday"}]}, "RFC 3339"),
        ({"op": "append", "items": [{"author": "a", "text": "x", "valid_at": "2026-10-14T16:00:00"}]}, "time zone"),
        ({"op": "append", "namespace": "../etc", "items": [{"author": "a", "text": "x"}]}, "namespace"),
        ({"op": "append", "import": True, "items": [{"author": "a", "text": "x"}]}, "valid_at is required"),
        ({"op": "query"}, "text is required"),
        ({"op": "query", "text": "x", "top_k": 101}, "top_k must be between 1 and 100"),
        ({"op": "query", "text": "x", "top_k": True}, "top_k must be an integer"),
        ({"op": "query", "text": "x", "max_tokens": 0}, "max_tokens"),
        ({"op": "query", "text": "x", "filter": {"kind": "message"}}, "list of kinds"),
        ({"op": "query", "text": "x", "filter": {"kind": ["chunk"]}}, "unknown kind"),
        ({"op": "query", "text": "x", "filter": {"thread": "a"}}, "unknown key"),
        ({"op": "query", "text": "x", "as_of": "nope"}, "RFC 3339"),
        ({"op": "query", "text": "x", "extra": 1}, "unknown key"),
    ],
)
def test_invalid_requests(mem, body, fragment):
    with pytest.raises(ApiError) as err:
        mem.handle(body)
    assert err.value.code == "invalid_argument"
    assert fragment in err.value.message
    assert err.value.body() == {"error": {"code": "invalid_argument", "message": err.value.message}}
    assert err.value.http_status == 400


def test_null_optional_keys_take_defaults(mem):
    append(mem, {"author": "a", "text": "hello world", "thread_id": None, "title": None, "retracts": None})
    resp = mem.handle(
        {"op": "query", "namespace": None, "text": "hello", "context": None, "filter": None,
         "as_of": None, "top_k": None, "max_tokens": None}
    )  # fmt: skip
    assert resp["items"][0]["thread_id"] == "default"


def test_client_ref_makes_resending_a_no_op(mem):
    first = append(mem, {"author": "agent", "text": "msg one", "client_ref": "m1"})["items"][0]
    again = append(
        mem,
        {"author": "agent", "text": "msg one", "client_ref": "m1"},
        {"author": "agent", "text": "msg two", "client_ref": "m2"},
    )["items"]
    assert again[0] == {**first, "status": "duplicate"}
    assert again[1]["status"] == "added"
    # the same client_ref from another author is a different item
    other = append(mem, {"author": "someone-else", "text": "msg one", "client_ref": "m1"})["items"][0]
    assert other["status"] == "added"
    assert mem.namespace("default").stats()["messages"] == 3


def test_duplicate_within_one_request(mem):
    items = append(
        mem, {"author": "a", "text": "x", "client_ref": "same"}, {"author": "a", "text": "x", "client_ref": "same"}
    )["items"]
    assert items[0]["status"] == "added" and items[1]["status"] == "duplicate"
    assert items[0]["id"] == items[1]["id"]


def test_created_at_strictly_increases_and_ids_sort_in_log_order(mem):
    ids, times = [], []
    for i in range(30):
        r = append(mem, {"author": "a", "text": f"item {i}"}, {"author": "a", "text": f"item {i} b"})
        for it in r["items"]:
            ids.append(it["id"])
            times.append(timeutil.parse(it["created_at"]))
    assert times == sorted(times) and len(set(times)) == len(times)
    assert ids == sorted(ids)


def test_valid_at_defaults_to_created_at(mem):
    r = append(mem, {"author": "a", "text": "when"})["items"][0]
    item = query(mem, "when")["items"][0]
    assert item["valid_at"] == item["created_at"] == r["created_at"]


def test_as_of_hides_later_items(mem):
    a = append(mem, {"author": "a", "text": "the cat sat on the mat"})["items"][0]
    t_between = timeutil.parse(a["created_at"])
    append(mem, {"author": "a", "text": "the cat ate the fish"})
    now = query(mem, "cat", max_tokens=1000)["items"]
    then = query(mem, "cat", max_tokens=1000, as_of=timeutil.format(t_between))
    assert len(now) == 2
    assert [i["id"] for i in then["items"]] == [a["id"]]
    assert then["as_of"] == timeutil.format(t_between)


def test_import_sets_created_at_to_valid_at(mem):
    r = append(
        mem,
        {"author": "user", "text": "old idea about gardens", "valid_at": "2024-03-01T10:00:00Z"},
        {"author": "user", "text": "older? no, same time is fine", "valid_at": "2024-03-01T10:00:00Z"},
        import_=True,
    )["items"]
    assert r[0]["created_at"] == "2024-03-01T10:00:00.000Z"
    seen = query(mem, "gardens", as_of="2024-03-02T00:00:00Z")["items"]
    assert seen and seen[0]["id"] == r[0]["id"]
    assert query(mem, "gardens", as_of="2024-02-01T00:00:00Z")["items"] == []


def test_import_rejects_decreasing_or_future_valid_at(mem):
    with pytest.raises(ApiError, match="must not decrease"):
        append(
            mem,
            {"author": "u", "text": "b", "valid_at": "2024-03-02T00:00:00Z"},
            {"author": "u", "text": "a", "valid_at": "2024-03-01T00:00:00Z"},
            import_=True,
        )
    with pytest.raises(ApiError, match="future"):
        append(mem, {"author": "u", "text": "x", "valid_at": "2999-01-01T00:00:00Z"}, import_=True)


def test_retraction_hides_from_its_created_at_onward(mem):
    orig = append(mem, {"author": "a", "text": "The launch is on Monday."})["items"][0]
    before = timeutil.format(timeutil.parse(orig["created_at"]))
    ret = append(mem, {"author": "a", "text": "Wrong date, withdrawn.", "retracts": [orig["id"]]})["items"][0]
    assert mem.flush(10)
    texts = [i["text"] for i in query(mem, "launch Monday", max_tokens=1000)["items"]]
    assert "The launch is on Monday." not in texts
    assert "Wrong date, withdrawn." in texts  # the reason is itself an item
    # as of before the retraction, the item is visible and not expired
    old = query(mem, "launch Monday", as_of=before)["items"]
    assert old[0]["id"] == orig["id"] and old[0]["expired_at"] is None
    # include_retracted shows it, with expired_at = the retraction's created_at
    shown = query(mem, "launch Monday", max_tokens=1000, filter={"include_retracted": True})["items"]
    match = [i for i in shown if i["id"] == orig["id"]][0]
    assert match["expired_at"] == ret["created_at"]


def test_retracting_a_message_retracts_its_pieces(mem):
    long = "\n\n".join(f"Paragraph {i} on budgets. " + "Costs grow every quarter. " * 30 for i in range(4))
    msg = append(mem, {"author": "a", "text": long})["items"][0]
    assert msg["pieces"] > 1
    append(mem, {"author": "a", "text": "withdrawn", "retracts": [msg["id"]]})
    assert all(i["source"]["id"] != msg["id"] for i in query(mem, "costs budgets", max_tokens=5000)["items"])


def test_retracting_an_unknown_id_fails_atomically(mem):
    with pytest.raises(ApiError) as err:
        append(
            mem,
            {"author": "a", "text": "this must not be stored"},
            {"author": "a", "text": "bad", "retracts": ["0192f3a1-7c2e-7d10-9b1a-5e2f0c8a4d31"]},
        )
    assert err.value.code == "not_found" and err.value.http_status == 404
    assert mem.namespace("default").stats()["messages"] == 0


def test_filters(mem):
    append(
        mem,
        {"author": "alice", "thread_id": "t1", "text": "apple pie recipe", "valid_at": "2026-01-01T00:00:00Z"},
        {"author": "bob", "thread_id": "t2", "text": "apple tart recipe", "valid_at": "2026-01-05T00:00:00Z"},
        {"author": "alice", "thread_id": "t2", "text": "apple crumble recipe", "valid_at": "2026-01-10T00:00:00Z"},
    )

    def texts(**flt):
        return sorted(i["text"] for i in query(mem, "apple recipe", max_tokens=1000, filter=flt)["items"])

    assert texts(author="alice") == ["apple crumble recipe", "apple pie recipe"]
    assert texts(thread_id="t2") == ["apple crumble recipe", "apple tart recipe"]
    assert texts(thread_id="nope") == []
    assert texts(valid_after="2026-01-05T00:00:00Z") == ["apple crumble recipe", "apple tart recipe"]
    assert texts(valid_before="2026-01-05T00:00:00Z") == ["apple pie recipe"]
    assert texts(valid_after="2026-01-02T00:00:00Z", valid_before="2026-01-10T00:00:00Z") == ["apple tart recipe"]
    assert texts(kind=["piece"]) == []
    assert len(texts(kind=["message"])) == 3
    assert texts(kind=["digest"]) == []


def test_top_k(mem):
    for i in range(15):
        append(mem, {"author": "a", "text": f"walnut {i}"})
    assert len(query(mem, "walnut", top_k=3)["items"]) == 3
    assert len(query(mem, "walnut", max_tokens=10_000)["items"]) == 10


def test_fill_skips_items_over_budget_and_counts_tokens(mem):
    tok = mem.tokenizer
    short = "zebra stripes are black and white"
    long = "zebra " + " ".join(f"word{i}" for i in range(60))
    append(mem, {"author": "a", "text": long}, {"author": "a", "text": short})
    n_short = len(tok.offsets(short))
    n_long = len(tok.offsets(long))
    budget = n_long + n_short - 1
    resp = query(mem, "zebra", max_tokens=budget, top_k=10)
    assert resp["tokens"] <= budget
    assert sum(len(tok.offsets(i["text"])) for i in resp["items"]) == resp["tokens"]
    assert len(resp["items"]) == 1  # the second item is skipped because it does not fit


def test_top_item_is_cut_to_budget_with_source_end_moved(mem):
    text = "kiwi " + " ".join(f"token{i}" for i in range(100))
    msg = append(mem, {"author": "a", "text": text})["items"][0]
    resp = query(mem, "kiwi", max_tokens=10)
    (item,) = resp["items"]
    assert resp["tokens"] == 10
    assert len(item["text"]) < len(text)
    assert text.startswith(item["text"])
    assert item["source"] == {"id": msg["id"], "title": None, "start": 0, "end": len(item["text"])}


def test_long_message_is_split_into_pieces_with_exact_spans(mem):
    paragraphs = [f"Section {i}. " + " ".join(f"fact{i}_{j} is stated here." for j in range(40)) for i in range(5)]
    text = "\n\n".join(paragraphs)
    msg = append(mem, {"author": "writer", "title": "Report", "text": text})["items"][0]
    assert msg["pieces"] > 1
    items = query(mem, "fact3_7 stated", top_k=100, max_tokens=100_000, filter={"kind": ["piece"]})["items"]
    assert len(items) == msg["pieces"]
    for item in items:
        src = item["source"]
        assert item["kind"] == "piece" and src["id"] == msg["id"] and src["title"] == "Report"
        assert text[src["start"] : src["end"]] == item["text"]
        assert len(mem.tokenizer.offsets(item["text"])) <= 256
        assert item["id"] != msg["id"]
    hit = query(mem, "fact3_7", top_k=1)["items"][0]
    assert "fact3_7 " in hit["text"]


def test_context_is_accepted_and_never_returned(mem):
    append(mem, {"author": "a", "text": "merger planning notes"})
    resp = query(mem, "merger", context="Planning the next merger with X")
    assert "Planning the next merger with X" not in str(resp)


def test_namespaces_are_separate(mem):
    append(mem, {"author": "a", "text": "secret plan alpha"}, namespace="one")
    append(mem, {"author": "a", "text": "public plan beta"}, namespace="two")
    assert [i["text"] for i in query(mem, "plan", namespace="one")["items"]] == ["secret plan alpha"]
    assert [i["text"] for i in query(mem, "plan", namespace="two")["items"]] == ["public plan beta"]
