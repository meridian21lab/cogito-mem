"""A floor for a trimmed Python hook: the same two queries and the same filtering, with only json, socket and re."""
import json, os, socket, sys, time
from cogito_mem.terms import query_terms, terms  # imports re only

def post(port, body):
    data = json.dumps(body).encode()
    s = socket.create_connection(("127.0.0.1", port), timeout=1)
    s.sendall(b"POST /v1/memory HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(data) + data)
    buf = b""
    while chunk := s.recv(65536):
        buf += chunk
    return json.loads(buf.split(b"\r\n\r\n", 1)[1])

hook = json.load(sys.stdin)
prompt, port = hook["prompt"][:2000], int(os.environ.get("COGITO_MEM_PORT", 7327))
words = query_terms(prompt)
q = {"op": "query", "namespace": os.environ.get("COGITO_MEM_NAMESPACE", "default"), "text": prompt, "top_k": 100, "max_tokens": 40000, "rerank": 0}
kept = [it for it in post(port, q)["items"] if it["score"] >= 0.6 and len(words & set(terms(it["text"]))) >= min(len(words), 3)]
stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 6 * 3600))
post(port, {**q, "filter": {"valid_after": stamp}})
print(json.dumps({"kept": len(kept)}))
