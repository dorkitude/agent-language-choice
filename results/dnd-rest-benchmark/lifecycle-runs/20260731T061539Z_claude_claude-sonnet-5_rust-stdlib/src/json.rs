//! Minimal, dependency-free JSON value model, parser, and formatting helpers.
//!
//! This target may not use serde or any other crate, so request bodies are
//! parsed into this small `Json` tree and responses are assembled as plain
//! `format!` strings by each handler module.

/// A parsed JSON value. Object keys preserve insertion order (a `Vec` of
/// pairs rather than a map) since request bodies are small and callers only
/// ever look up a handful of known keys.
#[derive(Debug, Clone)]
pub(crate) enum Json {
    Null,
    Bool(bool),
    Number(f64),
    String(String),
    Array(Vec<Json>),
    Object(Vec<(String, Json)>),
}

impl Json {
    pub(crate) fn as_object(&self) -> Option<&Vec<(String, Json)>> {
        match self {
            Json::Object(v) => Some(v),
            _ => None,
        }
    }

    pub(crate) fn as_array(&self) -> Option<&Vec<Json>> {
        match self {
            Json::Array(v) => Some(v),
            _ => None,
        }
    }

    pub(crate) fn as_f64(&self) -> Option<f64> {
        match self {
            Json::Number(n) => Some(*n),
            _ => None,
        }
    }

    pub(crate) fn as_str(&self) -> Option<&str> {
        match self {
            Json::String(s) => Some(s),
            _ => None,
        }
    }

    pub(crate) fn get(&self, key: &str) -> Option<&Json> {
        object_get(self.as_object()?, key)
    }
}

/// Looks up `key` in an already-unwrapped object's entry list. Shared by
/// `Json::get` and by handlers that pull a nested object out (e.g.
/// `abilities`, `armor`) and then need field lookups on it without
/// re-wrapping/cloning into a fresh `Json::Object`.
pub(crate) fn object_get<'a>(entries: &'a [(String, Json)], key: &str) -> Option<&'a Json> {
    entries.iter().find(|(k, _)| k == key).map(|(_, v)| v)
}

/// Extracts an integer field, rejecting values with a fractional part.
pub(crate) fn as_int(v: &Json) -> Option<i64> {
    let n = v.as_f64()?;
    if n.fract() == 0.0 {
        Some(n as i64)
    } else {
        None
    }
}

struct JsonParser {
    chars: Vec<char>,
    pos: usize,
}

impl JsonParser {
    fn new(src: &str) -> Self {
        JsonParser {
            chars: src.chars().collect(),
            pos: 0,
        }
    }

    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn advance(&mut self) -> Option<char> {
        let c = self.peek();
        if c.is_some() {
            self.pos += 1;
        }
        c
    }

    fn skip_ws(&mut self) {
        while let Some(c) = self.peek() {
            if c.is_whitespace() {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn parse(&mut self) -> Option<Json> {
        self.skip_ws();
        self.parse_value()
    }

    fn parse_value(&mut self) -> Option<Json> {
        self.skip_ws();
        match self.peek()? {
            '{' => self.parse_object(),
            '[' => self.parse_array(),
            '"' => self.parse_string().map(Json::String),
            't' | 'f' => self.parse_bool(),
            'n' => self.parse_null(),
            _ => self.parse_number(),
        }
    }

    fn parse_object(&mut self) -> Option<Json> {
        self.advance(); // {
        let mut entries = Vec::new();
        self.skip_ws();
        if self.peek() == Some('}') {
            self.advance();
            return Some(Json::Object(entries));
        }
        loop {
            self.skip_ws();
            let key = self.parse_string()?;
            self.skip_ws();
            if self.advance() != Some(':') {
                return None;
            }
            let value = self.parse_value()?;
            entries.push((key, value));
            self.skip_ws();
            match self.advance() {
                Some(',') => continue,
                Some('}') => break,
                _ => return None,
            }
        }
        Some(Json::Object(entries))
    }

    fn parse_array(&mut self) -> Option<Json> {
        self.advance(); // [
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(']') {
            self.advance();
            return Some(Json::Array(items));
        }
        loop {
            let value = self.parse_value()?;
            items.push(value);
            self.skip_ws();
            match self.advance() {
                Some(',') => continue,
                Some(']') => break,
                _ => return None,
            }
        }
        Some(Json::Array(items))
    }

    fn parse_string(&mut self) -> Option<String> {
        self.skip_ws();
        if self.advance() != Some('"') {
            return None;
        }
        let mut s = String::new();
        loop {
            let c = self.advance()?;
            match c {
                '"' => break,
                '\\' => {
                    let esc = self.advance()?;
                    match esc {
                        'n' => s.push('\n'),
                        't' => s.push('\t'),
                        'r' => s.push('\r'),
                        '"' => s.push('"'),
                        '\\' => s.push('\\'),
                        '/' => s.push('/'),
                        'u' => {
                            let mut code = 0u32;
                            for _ in 0..4 {
                                let h = self.advance()?;
                                code = code * 16 + h.to_digit(16)?;
                            }
                            if let Some(ch) = char::from_u32(code) {
                                s.push(ch);
                            }
                        }
                        other => s.push(other),
                    }
                }
                other => s.push(other),
            }
        }
        Some(s)
    }

    fn parse_bool(&mut self) -> Option<Json> {
        if self.chars[self.pos..].starts_with(&['t', 'r', 'u', 'e']) {
            self.pos += 4;
            Some(Json::Bool(true))
        } else if self.chars[self.pos..].starts_with(&['f', 'a', 'l', 's', 'e']) {
            self.pos += 5;
            Some(Json::Bool(false))
        } else {
            None
        }
    }

    fn parse_null(&mut self) -> Option<Json> {
        if self.chars[self.pos..].starts_with(&['n', 'u', 'l', 'l']) {
            self.pos += 4;
            Some(Json::Null)
        } else {
            None
        }
    }

    fn parse_number(&mut self) -> Option<Json> {
        let start = self.pos;
        if self.peek() == Some('-') {
            self.advance();
        }
        while let Some(c) = self.peek() {
            if c.is_ascii_digit() || c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-' {
                self.advance();
            } else {
                break;
            }
        }
        let s: String = self.chars[start..self.pos].iter().collect();
        s.parse::<f64>().ok().map(Json::Number)
    }
}

pub(crate) fn parse_json(src: &str) -> Option<Json> {
    let mut p = JsonParser::new(src);
    p.parse()
}

/// Formats a number the way the API expects: whole values render without a
/// trailing `.0` (e.g. `3`, not `3.0`), everything else uses Rust's default
/// float formatting.
pub(crate) fn fmt_num(n: f64) -> String {
    if n.is_finite() && n.fract() == 0.0 && n.abs() < 1e15 {
        format!("{}", n as i64)
    } else {
        format!("{}", n)
    }
}

/// Escapes a string for embedding in a hand-assembled JSON response body.
pub(crate) fn escape_json_string(s: &str) -> String {
    let mut out = String::new();
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}
