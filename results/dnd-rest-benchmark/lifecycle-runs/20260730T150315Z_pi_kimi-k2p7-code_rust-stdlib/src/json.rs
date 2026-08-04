/// Escape a string value for inclusion in a JSON string literal.
///
/// The implementation only handles backslashes and double quotes, which is the
/// subset required by the existing endpoints. It deliberately does not escape
/// control characters because none of the API responses produce them.
pub fn escape_json(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"")
}

/// Extract the value of a JSON string field.
///
/// Finds the first occurrence of `"key"`, then scans for the next colon and the
/// following double-quoted string. Does not support escaped quotes inside the
/// value; inputs are expected to be simple JSON objects.
pub fn extract_string<'a>(text: &'a str, key: &str) -> Option<&'a str> {
    let pattern = format!("\"{}\"", key);
    let pos = text.find(&pattern)? + pattern.len();
    let rest = &text[pos..];
    let colon = rest.find(':')? + 1;
    let rest = rest[colon..].trim_start();
    if !rest.starts_with('"') {
        return None;
    }
    let rest = &rest[1..];
    let end = rest.find('"')?;
    Some(&rest[..end])
}

/// Extract the value of a JSON integer field.
///
/// The value may start with an optional leading `-` and is terminated by the
/// first character that is neither a digit nor `-`. Multiple `-` signs are
/// rejected.
pub fn extract_int(text: &str, key: &str) -> Option<i64> {
    let pattern = format!("\"{}\"", key);
    let pos = text.find(&pattern)? + pattern.len();
    let rest = &text[pos..];
    let colon = rest.find(':')? + 1;
    let rest = rest[colon..].trim_start();
    let start = rest.find(|c: char| c == '-' || c.is_ascii_digit())?;
    let rest = &rest[start..];
    let mut end = rest.len();
    for (i, c) in rest.char_indices() {
        if !c.is_ascii_digit() && c != '-' {
            end = i;
            break;
        }
    }
    let num_str = &rest[..end];
    if num_str.matches('-').count() > 1 {
        return None;
    }
    if num_str == "-" {
        return None;
    }
    num_str.parse().ok()
}

/// Extract a JSON boolean field value.
pub fn extract_bool(text: &str, key: &str) -> Option<bool> {
    let pattern = format!("\"{}\"", key);
    let pos = text.find(&pattern)? + pattern.len();
    let rest = &text[pos..];
    let colon = rest.find(':')? + 1;
    let rest = rest[colon..].trim_start();
    if rest.starts_with("true") {
        Some(true)
    } else if rest.starts_with("false") {
        Some(false)
    } else {
        None
    }
}

/// Extract the body of a JSON array keyed by `key`.
///
/// Returns the content between the outer `[` and `]`, excluding the brackets.
/// Handles nested arrays by tracking bracket depth.
pub fn extract_array_content<'a>(text: &'a str, key: &str) -> Option<&'a str> {
    let pattern = format!("\"{}\"", key);
    let pos = text.find(&pattern)? + pattern.len();
    let rest = &text[pos..];
    let colon = rest.find(':')? + 1;
    let rest = rest[colon..].trim_start();
    if !rest.starts_with('[') {
        return None;
    }
    let rest = &rest[1..];
    let mut depth = 1;
    let mut end = rest.len();
    for (i, c) in rest.char_indices() {
        if c == '[' {
            depth += 1;
        } else if c == ']' {
            depth -= 1;
        }
        if depth == 0 {
            end = i;
            break;
        }
    }
    Some(&rest[..end])
}

/// Extract the body of a JSON object keyed by `key`.
///
/// Returns the content between the outer `{` and `}`, excluding the braces.
/// Handles nested objects by tracking brace depth.
pub fn extract_object_content<'a>(text: &'a str, key: &str) -> Option<&'a str> {
    let pattern = format!("\"{}\"", key);
    let pos = text.find(&pattern)? + pattern.len();
    let rest = &text[pos..];
    let colon = rest.find(':')? + 1;
    let rest = rest[colon..].trim_start();
    if !rest.starts_with('{') {
        return None;
    }
    let rest = &rest[1..];
    let mut depth = 1;
    let mut end = rest.len();
    for (i, c) in rest.char_indices() {
        if c == '{' {
            depth += 1;
        } else if c == '}' {
            depth -= 1;
        }
        if depth == 0 {
            end = i;
            break;
        }
    }
    Some(&rest[..end])
}

/// Extract the content of a top-level JSON array.
///
/// Used when parsing the SQLite JSON-mode output, which is a JSON array of
/// objects.
pub fn extract_top_array_content(text: &str) -> Option<&str> {
    let text = text.trim();
    if !text.starts_with('[') {
        return None;
    }
    let rest = &text[1..];
    let mut depth = 1;
    let mut end = rest.len();
    for (i, c) in rest.char_indices() {
        if c == '[' {
            depth += 1;
        } else if c == ']' {
            depth -= 1;
        }
        if depth == 0 {
            end = i;
            break;
        }
    }
    Some(&rest[..end])
}

/// Split a JSON object body into individual top-level object strings.
///
/// Each returned string includes the surrounding `{` and `}` characters.
/// Handles nested objects by tracking brace depth.
pub fn extract_objects(text: &str) -> Vec<&str> {
    let mut result = Vec::new();
    let mut start = 0;
    while let Some(pos) = text[start..].find('{') {
        let obj_start = start + pos;
        let mut depth = 1;
        let mut end = obj_start + 1;
        for (i, c) in text[end..].char_indices() {
            if c == '{' {
                depth += 1;
            } else if c == '}' {
                depth -= 1;
            }
            if depth == 0 {
                end = end + i;
                break;
            }
        }
        if end <= obj_start {
            break;
        }
        result.push(&text[obj_start..=end]);
        start = end + 1;
    }
    result
}

/// Extract a JSON array of string literals into a Vec of owned strings.
///
/// This is a stricter parser than `extract_array_content` because it validates
/// that each element is a quoted string and that elements are comma-separated.
pub fn extract_string_array(text: &str, key: &str) -> Option<Vec<String>> {
    let content = extract_array_content(text, key)?;
    let mut result = Vec::new();
    let mut rest = content.trim_start();
    while !rest.is_empty() {
        rest = rest.trim_start();
        if !rest.starts_with('"') {
            return None;
        }
        let inner = &rest[1..];
        let end = inner.find('"')?;
        result.push(inner[..end].to_string());
        rest = &inner[end + 1..];
        rest = rest.trim_start();
        if rest.is_empty() {
            break;
        }
        if !rest.starts_with(',') {
            return None;
        }
        rest = &rest[1..];
    }
    Some(result)
}
