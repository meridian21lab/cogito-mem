//! A Rust stand-in for cogito-mem's core (src/cogito_mem/store.py, keyword.py, embedding.py):
//! it opens the same log.sqlite3, rebuilds the same in-memory index, brings the vectors back from the
//! same embedding cache by the same sha256 keys, and ranks as `Namespace.search` does.
//!
//! `<root>` is a memory that `scripts/engines/bench.py fill` made (namespace `bench`, random vectors in its cache).
//! The write-up is docs/notes/rust_rewrite_20261111.md.
//!
//!   cogi bench <root> <queries.json> <qvecs.f32> <out.json>   open, then time the keyword, vector and hybrid lists
//!   cogi serve <root> <port>                                   POST /v1/memory, `op: query` only (keyword search)
//!   cogi fetch <https url>                                     an HTTPS GET (what downloading llama.cpp and the model needs)
//!   cogi redact                                                stdin with secrets replaced (what capture's redaction needs)

use cogi_probe::{format_ms, query_terms, terms};
use rusqlite::{Connection, OpenFlags};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::io::Read;
use std::path::Path;
use std::time::Instant;

const DIM: usize = 256;
const NEVER: i64 = i64::MAX;
const K1: f32 = 1.2;
const B: f32 = 0.75;
const RRF_K: f64 = 60.0;
const PREVIOUS_CONTEXT_CHARS: usize = 1000;
const SIDE_AUTHORS: [&str; 2] = ["actions", "tool"];

struct Msg {
    id: String,
    created: i64,
    valid: i64,
    thread_id: String,
    author: String,
    title: Option<String>,
    text: String,
    rows: Vec<u32>,
    prev: i32,
}

#[derive(Default)]
struct Ns {
    msgs: Vec<Msg>,
    msg_by_id: HashMap<String, u32>,
    row_by_id: HashMap<String, u32>,
    row_ids: Vec<String>,
    row_msg: Vec<u32>,
    row_span: Vec<(u32, u32)>,  // bytes of the message's text
    row_chars: Vec<(u32, u32)>, // the same span in code points, as the API reports it
    row_tokens: Vec<u32>,
    row_created: Vec<i64>,
    row_valid: Vec<i64>,
    row_thread: Vec<u32>,
    row_author: Vec<u32>,
    row_retracted: Vec<i64>,
    has_vec: Vec<bool>,
    vectors: Vec<f32>,
    halves: Vec<u16>, // the same vectors as stored: 16 bits each
    threads: HashMap<String, u32>,
    authors: HashMap<String, u32>,
    last_in_thread: HashMap<u32, i32>,
    term_ids: HashMap<String, u32>,
    postings: Vec<Vec<u32>>, // per term: row, tf, row, tf, ...
    lengths: Vec<f32>,
    total_length: f64,
}

fn code(table: &mut HashMap<String, u32>, key: &str) -> u32 {
    if let Some(&c) = table.get(key) {
        return c;
    }
    let c = table.len() as u32;
    table.insert(key.to_string(), c);
    c
}

/// Byte offsets of the given code-point offsets (ascending) in `text`.
fn byte_offsets(text: &str, chars: &[u32]) -> Vec<u32> {
    let mut out = Vec::with_capacity(chars.len());
    let mut want = chars.iter().peekable();
    let mut n = 0u32;
    for (b, _) in text.char_indices() {
        while want.peek().is_some_and(|&&c| c == n) {
            out.push(b as u32);
            want.next();
        }
        n += 1;
    }
    for _ in want {
        out.push(text.len() as u32);
    }
    out
}

impl Ns {
    fn open(folder: &Path) -> rusqlite::Result<Ns> {
        let db = Connection::open_with_flags(folder.join("log.sqlite3"), OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let mut ns = Ns::default();
        let mut stmt = db.prepare(
            "SELECT id, created_at, valid_at, thread_id, author, title, text, retracts, pieces, imported FROM log ORDER BY seq",
        )?;
        let mut rows = stmt.query([])?;
        let mut row_terms: Vec<u32> = Vec::new();
        while let Some(r) = rows.next()? {
            let id: String = r.get(0)?;
            let (created, valid): (i64, i64) = (r.get(1)?, r.get(2)?);
            let (thread_id, author): (String, String) = (r.get(3)?, r.get(4)?);
            let title: Option<String> = r.get(5)?;
            let text: String = r.get(6)?;
            let retracts: String = r.get(7)?;
            let pieces: Value = serde_json::from_str(&r.get::<_, String>(8)?).unwrap_or(Value::Null);
            let idx = ns.msgs.len() as u32;
            let thread = code(&mut ns.threads, &thread_id);
            let author_code = code(&mut ns.authors, &author);
            let prev = ns.last_in_thread.get(&thread).copied().unwrap_or(-1);
            if !SIDE_AUTHORS.contains(&author.as_str()) {
                ns.last_in_thread.insert(thread, idx as i32);
            }
            let empty = Vec::new();
            let list = pieces.as_array().unwrap_or(&empty);
            let mut marks: Vec<u32> = Vec::with_capacity(list.len() * 2);
            for p in list {
                marks.push(p[1].as_u64().unwrap_or(0) as u32);
                marks.push(p[2].as_u64().unwrap_or(0) as u32);
            }
            let bytes = if list.len() == 1 && marks[0] == 0 { vec![0, text.len() as u32] } else { byte_offsets_any(&text, &marks) };
            let mut msg_rows = Vec::with_capacity(list.len());
            for (k, p) in list.iter().enumerate() {
                let row = ns.row_ids.len() as u32;
                let piece_id = p[0].as_str().unwrap_or("").to_string();
                ns.row_by_id.insert(piece_id.clone(), row);
                ns.row_ids.push(piece_id);
                msg_rows.push(row);
                ns.row_msg.push(idx);
                let (a, b) = (bytes[2 * k] as usize, bytes[2 * k + 1] as usize);
                ns.row_span.push((a as u32, b as u32));
                ns.row_chars.push((marks[2 * k], marks[2 * k + 1]));
                ns.row_tokens.push(p[3].as_u64().unwrap_or(0) as u32);
                ns.row_created.push(created);
                ns.row_valid.push(valid);
                ns.row_thread.push(thread);
                ns.row_author.push(author_code);
                ns.row_retracted.push(NEVER);
                ns.has_vec.push(false);
                // BM25 over "author: title\ntext", as Namespace._index gives it (index_author is the default).
                let seg = &text[a..b];
                let searchable = match &title {
                    Some(t) if !t.is_empty() => format!("{author}: {t}\n{seg}"),
                    _ => format!("{author}: {seg}"),
                };
                row_terms.clear();
                let (term_ids, postings) = (&mut ns.term_ids, &mut ns.postings);
                terms(&searchable, |t| {
                    let tid = match term_ids.get(t) {
                        Some(&tid) => tid,
                        None => {
                            let tid = postings.len() as u32;
                            term_ids.insert(t.to_string(), tid);
                            postings.push(Vec::new());
                            tid
                        }
                    };
                    row_terms.push(tid);
                });
                let length = row_terms.len() as f32;
                ns.lengths.push(length);
                ns.total_length += length as f64;
                row_terms.sort_unstable();
                let mut i = 0;
                while i < row_terms.len() {
                    let mut j = i;
                    while j < row_terms.len() && row_terms[j] == row_terms[i] {
                        j += 1;
                    }
                    let list = &mut ns.postings[row_terms[i] as usize];
                    list.push(row);
                    list.push((j - i) as u32);
                    i = j;
                }
            }
            ns.msg_by_id.insert(id.clone(), idx);
            ns.msgs.push(Msg { id, created, valid, thread_id, author, title, text, rows: msg_rows, prev });
            if retracts.len() > 2 {
                for target in serde_json::from_str::<Vec<String>>(&retracts).unwrap_or_default() {
                    let hit: Vec<u32> = match (ns.msg_by_id.get(&target), ns.row_by_id.get(&target)) {
                        (Some(&m), _) => ns.msgs[m as usize].rows.clone(),
                        (None, Some(&row)) => vec![row],
                        _ => vec![],
                    };
                    for row in hit {
                        let at = &mut ns.row_retracted[row as usize];
                        *at = (*at).min(created);
                    }
                }
            }
        }
        Ok(ns)
    }

    fn row_text(&self, row: usize) -> &str {
        let (a, b) = self.row_span[row];
        &self.msgs[self.row_msg[row] as usize].text[a as usize..b as usize]
    }

    /// The prompt EmbeddingGemma was given for this row (Namespace.prompts with doc_context="previous",
    /// doc_author=True, and embedding.doc_prompt), so its sha256 finds the vector in the cache.
    fn prompt(&self, row: usize) -> String {
        let msg = &self.msgs[self.row_msg[row] as usize];
        let pos = msg.rows.iter().position(|&r| r as usize == row).unwrap();
        let before: Option<(&str, &str)> = if pos > 0 {
            Some((&msg.author, self.row_text(msg.rows[pos - 1] as usize)))
        } else if msg.prev >= 0 && self.msgs[msg.prev as usize].author != msg.author {
            let p = &self.msgs[msg.prev as usize];
            Some((&p.author, &p.text))
        } else {
            None
        };
        let mut text = format!("{}: {}", msg.author, self.row_text(row));
        if let Some((author, mut prev)) = before {
            let n = prev.chars().count();
            if n > PREVIOUS_CONTEXT_CHARS {
                let cut = prev.char_indices().nth(n - PREVIOUS_CONTEXT_CHARS).map(|(b, _)| b).unwrap_or(0);
                prev = &prev[cut..];
                if let Some(space) = prev.chars().position(|c| c == ' ') {
                    if space < 100 {
                        let b = prev.char_indices().nth(space + 1).map(|(b, _)| b).unwrap_or(prev.len());
                        prev = &prev[b..];
                    }
                }
            }
            if !prev.is_empty() {
                text = format!("{author}: {prev}\n\n{text}");
            }
        }
        let title: String = msg.title.as_deref().unwrap_or("").trim().chars().take(200).collect();
        format!("title: {} | text: {}", if title.is_empty() { "none" } else { &title }, text)
    }

    fn load_vectors(&mut self, cache: &Path, model: &str) -> rusqlite::Result<usize> {
        let db = Connection::open_with_flags(cache, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let mut stmt = db.prepare("SELECT vec FROM vectors WHERE key = ?1")?;
        let n = self.row_ids.len();
        self.vectors = vec![0f32; n * DIM];
        self.halves = vec![0u16; n * DIM];
        let mut found = 0;
        let (mut t_prompt, mut t_sha, mut t_sql) = (0f64, 0f64, 0f64);
        for row in 0..n {
            let t = Instant::now();
            let prompt = self.prompt(row);
            t_prompt += t.elapsed().as_secs_f64();
            let t = Instant::now();
            let mut h = Sha256::new();
            h.update(model.as_bytes());
            h.update([0u8]);
            h.update(prompt.as_bytes());
            let key = h.finalize();
            t_sha += t.elapsed().as_secs_f64();
            let t = Instant::now();
            let blob: Option<Vec<u8>> = stmt.query_row([&key[..]], |r| r.get(0)).ok();
            t_sql += t.elapsed().as_secs_f64();
            if row + 1 == n {
                eprintln!("vectors: prompts {t_prompt:.2} s, sha256 {t_sha:.2} s, cache lookups {t_sql:.2} s");
            }
            if let Some(blob) = blob.filter(|b| b.len() == DIM * 2) {
                for (i, pair) in blob.chunks_exact(2).enumerate() {
                    let bits = u16::from_le_bytes([pair[0], pair[1]]);
                    self.halves[row * DIM + i] = bits;
                    self.vectors[row * DIM + i] = half::f16::from_bits(bits).to_f32();
                }
                self.has_vec[row] = true;
                found += 1;
            }
        }
        Ok(found)
    }

    #[inline]
    fn visible(&self, row: usize, as_of: i64) -> bool {
        self.row_created[row] <= as_of && self.row_retracted[row] > as_of
    }

    /// BM25Index.scores, then the mask and Namespace._top: the best `pool` visible rows.
    fn keyword(&self, text: &str, as_of: i64, pool: usize, acc: &mut Vec<f32>) -> Vec<(f32, u32)> {
        let n = self.row_ids.len();
        acc.clear();
        acc.resize(n, 0.0);
        let avg = (self.total_length / n.max(1) as f64) as f32;
        let mut touched: Vec<u32> = Vec::new();
        for term in query_terms(text) {
            let Some(&tid) = self.term_ids.get(&term) else { continue };
            let list = &self.postings[tid as usize];
            let df = (list.len() / 2) as f32;
            let idf = (1.0 + (n as f32 - df + 0.5) / (df + 0.5)).ln();
            for pair in list.chunks_exact(2) {
                let (row, tf) = (pair[0] as usize, pair[1] as f32);
                let denom = tf + K1 * (1.0 - B + B * self.lengths[row] / avg);
                if acc[row] == 0.0 {
                    touched.push(row as u32);
                }
                acc[row] += idf * tf * (K1 + 1.0) / denom;
            }
        }
        let scored: Vec<(f32, u32)> = touched.iter().filter(|&&r| self.visible(r as usize, as_of)).map(|&r| (acc[r as usize], r)).collect();
        top(scored, pool)
    }

    /// The exact dot product with every visible vector, then the best `pool`.
    fn vector(&self, q: &[f32], as_of: i64, pool: usize, sims: &mut Vec<f32>, half: bool) -> Vec<(f32, u32)> {
        let n = self.row_ids.len();
        sims.clear();
        sims.resize(n, 0.0);
        if half {
            dots_f16(&self.halves, q, sims);
        } else {
            dots(&self.vectors, q, sims);
        }
        let scored: Vec<(f32, u32)> = (0..n).filter(|&r| self.has_vec[r] && self.visible(r, as_of)).map(|r| (sims[r], r as u32)).collect();
        top(scored, pool)
    }
}

fn byte_offsets_any(text: &str, marks: &[u32]) -> Vec<u32> {
    // Piece spans come as start, end, start, end...; map each through a sorted copy.
    let mut sorted = marks.to_vec();
    sorted.sort_unstable();
    sorted.dedup();
    let bytes = byte_offsets(text, &sorted);
    marks.iter().map(|m| bytes[sorted.binary_search(m).unwrap()]).collect()
}

/// Namespace._top: the k best by score, ties by row.
fn top(mut scored: Vec<(f32, u32)>, k: usize) -> Vec<(f32, u32)> {
    let by = |a: &(f32, u32), b: &(f32, u32)| b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1));
    if scored.len() > k {
        scored.select_nth_unstable_by(k - 1, by);
        scored.truncate(k);
    }
    scored.sort_unstable_by(by);
    scored
}

/// Reciprocal rank fusion as in Namespace.search: (row, score scaled so first in every list is 1).
fn fuse(lists: &[&[(f32, u32)]], pool: usize) -> Vec<(u32, f32)> {
    let mut fused: HashMap<u32, (f64, u32)> = HashMap::new(); // f64, as Python adds them
    for list in lists {
        for (i, &(_, row)) in list.iter().enumerate() {
            let rank = i as u32 + 1;
            let e = fused.entry(row).or_insert((0.0, rank));
            e.0 += 1.0 / (RRF_K + rank as f64);
            e.1 = e.1.min(rank);
        }
    }
    let best = lists.len().max(1) as f64 / (RRF_K + 1.0);
    let mut order: Vec<(u32, f64, u32)> = fused.into_iter().map(|(row, (s, first))| (row, s, first)).collect();
    order.sort_unstable_by(|a, b| b.1.partial_cmp(&a.1).unwrap().then(a.2.cmp(&b.2)).then(b.0.cmp(&a.0)));
    order.truncate(pool);
    order.into_iter().map(|(row, s, _)| (row, (s / best).min(1.0) as f32)).collect()
}

#[inline(always)]
fn dot(a: &[f32], b: &[f32]) -> f32 {
    let mut acc = [0f32; 16];
    for (x, y) in a.chunks_exact(16).zip(b.chunks_exact(16)) {
        for i in 0..16 {
            acc[i] += x[i] * y[i];
        }
    }
    acc.iter().sum()
}

#[inline(always)]
fn dots_plain(m: &[f32], q: &[f32], out: &mut [f32]) {
    for (row, o) in m.chunks_exact(DIM).zip(out.iter_mut()) {
        *o = dot(row, q);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2,fma")]
unsafe fn dots_avx2(m: &[f32], q: &[f32], out: &mut [f32]) {
    dots_plain(m, q, out)
}

/// One build for every x86-64 machine: AVX2 is chosen when the program runs, as numpy's BLAS does.
fn dots(m: &[f32], q: &[f32], out: &mut [f32]) {
    #[cfg(target_arch = "x86_64")]
    if is_x86_feature_detected!("avx2") && is_x86_feature_detected!("fma") {
        return unsafe { dots_avx2(m, q, out) };
    }
    dots_plain(m, q, out)
}

/// The same product over the vectors as stored (16 bits each): half the memory to read.
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2,fma,f16c")]
unsafe fn dots_f16_avx2(m: &[u16], q: &[f32], out: &mut [f32]) {
    use std::arch::x86_64::*;
    unsafe {
        for (r, o) in out.iter_mut().enumerate() {
            let base = m.as_ptr().add(r * DIM);
            let (mut a0, mut a1) = (_mm256_setzero_ps(), _mm256_setzero_ps());
            let mut i = 0;
            while i < DIM {
                let v0 = _mm256_cvtph_ps(_mm_loadu_si128(base.add(i) as *const __m128i));
                let v1 = _mm256_cvtph_ps(_mm_loadu_si128(base.add(i + 8) as *const __m128i));
                a0 = _mm256_fmadd_ps(v0, _mm256_loadu_ps(q.as_ptr().add(i)), a0);
                a1 = _mm256_fmadd_ps(v1, _mm256_loadu_ps(q.as_ptr().add(i + 8)), a1);
                i += 16;
            }
            let a = _mm256_add_ps(a0, a1);
            let s = _mm_add_ps(_mm256_extractf128_ps(a, 1), _mm256_castps256_ps128(a));
            let s = _mm_hadd_ps(s, s);
            *o = _mm_cvtss_f32(_mm_hadd_ps(s, s));
        }
    }
}

fn dots_f16(m: &[u16], q: &[f32], out: &mut [f32]) {
    #[cfg(target_arch = "x86_64")]
    if is_x86_feature_detected!("avx2") && is_x86_feature_detected!("fma") && is_x86_feature_detected!("f16c") {
        return unsafe { dots_f16_avx2(m, q, out) };
    }
    for (r, o) in out.iter_mut().enumerate() {
        *o = m[r * DIM..(r + 1) * DIM].iter().zip(q).map(|(&h, &x)| half::f16::from_bits(h).to_f32() * x).sum();
    }
}

fn rss_mb() -> f64 {
    let statm = std::fs::read_to_string("/proc/self/statm").unwrap_or_default();
    statm.split_whitespace().nth(1).and_then(|p| p.parse::<f64>().ok()).unwrap_or(0.0) * 4096.0 / 1048576.0
}

fn stats(ms: &mut [f64]) -> Value {
    ms.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = ms.len();
    let p95 = ms[(((0.95 * n as f64).round() as usize).max(1) - 1).min(n - 1)];
    let median = if n % 2 == 1 { ms[n / 2] } else { (ms[n / 2 - 1] + ms[n / 2]) / 2.0 };
    json!({"n": n, "median_ms": (median * 1000.0).round() / 1000.0, "p95_ms": (p95 * 1000.0).round() / 1000.0,
           "max_ms": (ms[n - 1] * 1000.0).round() / 1000.0})
}

fn bench(args: &[String]) {
    let root = Path::new(&args[0]);
    let base = rss_mb();
    let t0 = Instant::now();
    let mut ns = Ns::open(&root.join("memory").join("bench")).expect("open the log");
    let open_s = t0.elapsed().as_secs_f64();
    let rss_open = rss_mb();
    let found = ns.load_vectors(&root.join("cache").join("embeddings.sqlite3"), "random-sha256-v1").expect("open the cache");
    let ready_s = t0.elapsed().as_secs_f64();
    let n = ns.row_ids.len();
    eprintln!("open {open_s:.3} s, vectors {found}/{n} at {ready_s:.3} s, {} terms, rss {:.0} MB", ns.term_ids.len(), rss_mb());

    let texts: Vec<String> = serde_json::from_str(&std::fs::read_to_string(&args[1]).unwrap()).unwrap();
    let raw = std::fs::read(&args[2]).unwrap();
    let qvecs: Vec<f32> = raw.chunks_exact(4).map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]])).collect();
    let as_of = ns.row_created.iter().copied().max().unwrap_or(0) + 1;
    let pool = 100;
    let (mut acc, mut sims) = (Vec::new(), Vec::new());
    let mut lists: HashMap<&str, Vec<Vec<u32>>> = HashMap::new();
    let mut timing = serde_json::Map::new();
    for lane in ["keyword", "vector", "hybrid", "vector_f16", "hybrid_f16"] {
        let mut ms = Vec::with_capacity(texts.len());
        for (i, text) in texts.iter().enumerate() {
            let q = &qvecs[i * DIM..(i + 1) * DIM];
            let t = Instant::now();
            let rows: Vec<u32> = match lane {
                "keyword" => ns.keyword(text, as_of, pool, &mut acc).iter().map(|x| x.1).collect(),
                "vector" | "vector_f16" => ns.vector(q, as_of, pool, &mut sims, lane.ends_with("f16")).iter().map(|x| x.1).collect(),
                _ => {
                    let v = ns.vector(q, as_of, pool, &mut sims, lane.ends_with("f16"));
                    let k = ns.keyword(text, as_of, pool, &mut acc);
                    fuse(&[&v, &k], pool).iter().map(|x| x.0).collect()
                }
            };
            ms.push(t.elapsed().as_secs_f64() * 1000.0);
            if i < 200 {
                lists.entry(lane).or_default().push(rows);
            }
        }
        timing.insert(format!("all/{lane}"), stats(&mut ms));
    }
    let out = json!({"engine": "rust-probe", "items": n, "messages": ns.msgs.len(), "terms": ns.term_ids.len(),
        "open_s": (open_s * 1000.0).round() / 1000.0, "ready_s": (ready_s * 1000.0).round() / 1000.0, "vectors_found": found,
        "rss_mb": {"before": base, "after_open": rss_open, "after_queries": rss_mb()}, "query": timing, "lists": lists});
    std::fs::write(&args[3], out.to_string()).unwrap();
    let mut brief = out.clone();
    brief.as_object_mut().unwrap().remove("lists");
    println!("{}", serde_json::to_string_pretty(&brief).unwrap());
}

/// `op: query` as Memory._query answers it with no embedding model: keyword list, fused alone, then `fill`.
fn answer(ns: &Ns, body: &Value, acc: &mut Vec<f32>) -> Value {
    let t0 = Instant::now();
    let text = body["text"].as_str().unwrap_or("");
    let top_k = body["top_k"].as_u64().unwrap_or(300) as usize;
    let max_tokens = body["max_tokens"].as_u64().unwrap_or(1000) as u32;
    let as_of = ns.row_created.iter().copied().max().unwrap_or(0);
    let pool = top_k.saturating_mul(3).max(100);
    let cands = fuse(&[&ns.keyword(text, as_of, pool, acc)], pool);
    let mut items = Vec::new();
    let mut total = 0u32;
    for (row, score) in cands {
        if items.len() >= top_k || total >= max_tokens {
            break;
        }
        let row = row as usize;
        let n_tokens = ns.row_tokens[row];
        if !items.is_empty() && total + n_tokens > max_tokens {
            continue;
        }
        let msg = &ns.msgs[ns.row_msg[row] as usize];
        let (start, end) = ns.row_chars[row];
        items.push(json!({"id": ns.row_ids[row], "kind": if msg.rows.len() == 1 { "message" } else { "piece" }, "text": ns.row_text(row),
            "score": (score as f64 * 10000.0).round() / 10000.0, "similarity": null, "author": msg.author, "thread_id": msg.thread_id,
            "valid_at": format_ms(msg.valid), "created_at": format_ms(msg.created), "expired_at": null,
            "source": {"id": msg.id, "title": msg.title, "start": start, "end": end}}));
        total += n_tokens;
    }
    json!({"items": items, "as_of": format_ms(as_of), "tokens": total, "took_ms": (t0.elapsed().as_secs_f64() * 1e6).round() / 1000.0})
}

fn serve(args: &[String]) {
    let root = Path::new(&args[0]);
    let t0 = Instant::now();
    let ns = Ns::open(&root.join("memory").join("bench")).expect("open the log");
    let server = tiny_http::Server::http(format!("127.0.0.1:{}", args[1])).expect("listen");
    eprintln!("cogi (rust probe) serving {} items on 127.0.0.1:{} after {:.2} s", ns.row_ids.len(), args[1], t0.elapsed().as_secs_f64());
    let mut acc = Vec::new();
    let json_type = tiny_http::Header::from_bytes(&b"Content-Type"[..], &b"application/json; charset=utf-8"[..]).unwrap();
    for mut request in server.incoming_requests() {
        let mut body = String::new();
        let _ = request.as_reader().read_to_string(&mut body);
        let reply = match serde_json::from_str::<Value>(&body) {
            Ok(v) if v["op"] == "query" => answer(&ns, &v, &mut acc),
            _ => json!({"error": {"code": "invalid_argument", "message": "this probe answers op: query only"}}),
        };
        let _ = request.respond(tiny_http::Response::from_string(reply.to_string()).with_header(json_type.clone()));
    }
}

fn redact() {
    // The kind of patterns capture uses to keep secrets out of the memory.
    let re = regex::Regex::new(r#"(?i)(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|(?:password|passwd|secret|token)\s*[=:]\s*\S+)"#).unwrap();
    let mut input = String::new();
    let _ = std::io::stdin().read_to_string(&mut input);
    print!("{}", re.replace_all(&input, "[redacted]"));
}

fn fetch(url: &str) {
    match ureq::get(url).call() {
        Ok(resp) => {
            let status = resp.status();
            let mut n = 0u64;
            let mut buf = [0u8; 1 << 16];
            let mut reader = resp.into_reader();
            while let Ok(k) = reader.read(&mut buf) {
                if k == 0 {
                    break;
                }
                n += k as u64;
            }
            println!("{status} {n} bytes");
        }
        Err(e) => println!("error: {e}"),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("bench") if args.len() == 5 => bench(&args[1..]),
        Some("serve") if args.len() == 3 => serve(&args[1..]),
        Some("fetch") if args.len() == 2 => fetch(&args[1]),
        Some("redact") => redact(),
        _ => eprintln!("usage: cogi bench <root> <queries.json> <qvecs.f32> <out.json> | serve <root> <port> | fetch <url> | redact"),
    }
}
