//! What the hook and the core share: cogito-mem's terms (src/cogito_mem/terms.py) and its dates.

use std::collections::HashSet;

/// Function words dropped from queries, not from the index (terms.STOPWORDS).
pub const STOPWORDS: &str = "a about above after again against all am an and any are as at be because been before being below \
between both but by can could did do does doing don down during each few for from further had has \
have having he her here hers herself him himself his how i if in into is it its itself just me \
more most my myself no nor not now of off on once only or other our ours ourselves out over own \
same she should so some such than that the their theirs them themselves then there these they this \
those through to too under until up very was we were what when where which while who whom why will \
with would you your yours yourself yourselves s t ll re ve d m";

#[inline]
fn is_cjk(c: char) -> bool {
    matches!(c as u32, 0x3040..=0x30ff | 0x3400..=0x4dbf | 0x4e00..=0x9fff | 0xac00..=0xd7af | 0xf900..=0xfaff)
}

/// Python's `[^\W_]`: letters and numbers. (Rust also counts a few combining marks; English text has none.)
#[inline]
fn is_word(c: char) -> bool {
    c.is_alphanumeric()
}

/// `terms.terms`: lower-cased words; a CJK character that starts a token is a term of its own.
pub fn terms(text: &str, mut emit: impl FnMut(&str)) {
    let lower = text.to_lowercase();
    let mut start: Option<usize> = None;
    for (i, c) in lower.char_indices() {
        match start {
            Some(s) => {
                if !is_word(c) {
                    emit(&lower[s..i]);
                    start = None;
                }
            }
            None => {
                if is_cjk(c) {
                    emit(&lower[i..i + c.len_utf8()]);
                } else if is_word(c) {
                    start = Some(i);
                }
            }
        }
    }
    if let Some(s) = start {
        emit(&lower[s..]);
    }
}

pub fn term_set(text: &str) -> HashSet<String> {
    let mut out = HashSet::new();
    terms(text, |t| {
        out.insert(t.to_string());
    });
    out
}

/// `terms.query_terms`: the query's terms without function words, unless nothing else is left.
pub fn query_terms(text: &str) -> HashSet<String> {
    let all = term_set(text);
    let stop: HashSet<&str> = STOPWORDS.split_whitespace().collect();
    let content: HashSet<String> = all.iter().filter(|t| !stop.contains(t.as_str())).cloned().collect();
    if content.is_empty() { all } else { content }
}

/// Milliseconds since the epoch as `2026-11-11T12:00:00.000Z` (timeutil.format).
pub fn format_ms(ms: i64) -> String {
    let secs = ms.div_euclid(1000);
    let milli = ms.rem_euclid(1000);
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    // Civil date from days since 1970-01-01 (Howard Hinnant's algorithm).
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z", y, m, d, rem / 3600, rem % 3600 / 60, rem % 60, milli)
}

/// A rough token count shaped like tokenizer.ApproxTokenizer: words in 7-letter chunks, digits and marks one each.
pub fn approx_tokens(text: &str) -> usize {
    let mut n = 0;
    let mut letters = 0usize;
    let mut spaces = 0usize;
    let mut newline = false;
    let flush = |letters: &mut usize, spaces: &mut usize, newline: &mut bool, n: &mut usize| {
        if *letters > 0 {
            *n += (*letters + 6) / 7;
            *letters = 0;
        }
        if *spaces > 0 {
            if *newline || *spaces > 1 {
                *n += 1;
            }
            *spaces = 0;
            *newline = false;
        }
    };
    for c in text.chars() {
        if c.is_whitespace() {
            if letters > 0 {
                flush(&mut letters, &mut spaces, &mut newline, &mut n);
            }
            spaces += 1;
            newline |= c == '\n';
        } else if c.is_alphabetic() && !is_cjk(c) {
            if spaces > 0 {
                flush(&mut letters, &mut spaces, &mut newline, &mut n);
            }
            letters += 1;
        } else {
            flush(&mut letters, &mut spaces, &mut newline, &mut n);
            n += 1;
        }
    }
    flush(&mut letters, &mut spaces, &mut newline, &mut n);
    n
}
