//! Dice rolling and roll-comparison endpoints: `NdM+K` expression stats,
//! ability-check success against a DC, and initiative ordering. These are
//! stateless, pure calculations over the request body.

use std::net::TcpStream;

use crate::http::{bad_request, respond};
use crate::json::{escape_json_string, fmt_num, parse_json};

pub(crate) fn handle_dice_stats(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };
    let expr = match json.get("expression").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return bad_request(stream, "missing expression"),
    };

    match parse_dice_expression(expr) {
        Some((count, sides, modifier)) => {
            let min = count * 1 + modifier;
            let max = count * sides + modifier;
            let average = (count as f64) * ((sides as f64) + 1.0) / 2.0 + (modifier as f64);
            let out = format!(
                r#"{{"dice_count":{},"sides":{},"modifier":{},"min":{},"max":{},"average":{}}}"#,
                count,
                sides,
                modifier,
                min,
                max,
                fmt_num(average)
            );
            respond(stream, 200, &out)
        }
        None => bad_request(stream, "invalid expression"),
    }
}

/// Parses a `NdM`, `NdM+K`, or `NdM-K` dice expression (e.g. `"2d6+3"`) into
/// `(count, sides, modifier)`. Whitespace around the expression is trimmed;
/// everything else must be digits either side of the `d`/`D` separator.
fn parse_dice_expression(expr: &str) -> Option<(i64, i64, i64)> {
    let expr = expr.trim();
    let d_pos = expr.find('d').or_else(|| expr.find('D'))?;
    let count_str = &expr[..d_pos];
    let rest = &expr[d_pos + 1..];

    if count_str.is_empty() || !count_str.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let count: i64 = count_str.parse().ok()?;
    if count <= 0 {
        return None;
    }

    let mut sign_pos = None;
    for (i, c) in rest.char_indices() {
        if i == 0 {
            continue;
        }
        if c == '+' || c == '-' {
            sign_pos = Some(i);
            break;
        }
    }

    let (sides_str, modifier) = match sign_pos {
        Some(i) => {
            let sides_str = &rest[..i];
            let mod_str = &rest[i..];
            let sign = if mod_str.starts_with('-') { -1 } else { 1 };
            let mod_digits = &mod_str[1..];
            if mod_digits.is_empty() || !mod_digits.chars().all(|c| c.is_ascii_digit()) {
                return None;
            }
            let modifier: i64 = mod_digits.parse().ok()?;
            (sides_str, sign * modifier)
        }
        None => (rest, 0),
    };

    if sides_str.is_empty() || !sides_str.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let sides: i64 = sides_str.parse().ok()?;
    if sides <= 0 {
        return None;
    }

    Some((count, sides, modifier))
}

pub(crate) fn handle_ability_check(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };
    let roll = json.get("roll").and_then(|v| v.as_f64());
    let modifier = json.get("modifier").and_then(|v| v.as_f64());
    let dc = json.get("dc").and_then(|v| v.as_f64());

    let (roll, modifier, dc) = match (roll, modifier, dc) {
        (Some(r), Some(m), Some(d)) => (r, m, d),
        _ => return bad_request(stream, "missing fields"),
    };

    let total = roll + modifier;
    let success = total >= dc;
    let margin = total - dc;

    let out = format!(
        r#"{{"total":{},"success":{},"margin":{}}}"#,
        fmt_num(total),
        success,
        fmt_num(margin)
    );
    respond(stream, 200, &out)
}

pub(crate) fn handle_initiative_order(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };
    let combatants = match json.get("combatants").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return bad_request(stream, "missing combatants"),
    };

    struct Combatant {
        name: String,
        dex: f64,
        score: f64,
    }

    let mut entries: Vec<Combatant> = Vec::new();
    for c in combatants {
        let name = match c.get("name").and_then(|v| v.as_str()) {
            Some(s) => s.to_string(),
            None => return bad_request(stream, "invalid combatant"),
        };
        let dex = match c.get("dex").and_then(|v| v.as_f64()) {
            Some(v) => v,
            None => return bad_request(stream, "invalid combatant"),
        };
        let roll = match c.get("roll").and_then(|v| v.as_f64()) {
            Some(v) => v,
            None => return bad_request(stream, "invalid combatant"),
        };
        entries.push(Combatant {
            name,
            dex,
            score: roll + dex,
        });
    }

    // Highest score first; ties broken by higher DEX, then name for a
    // fully deterministic order.
    entries.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap()
            .then_with(|| b.dex.partial_cmp(&a.dex).unwrap())
            .then_with(|| a.name.cmp(&b.name))
    });

    let items: Vec<String> = entries
        .iter()
        .map(|c| {
            format!(
                r#"{{"name":"{}","score":{}}}"#,
                escape_json_string(&c.name),
                fmt_num(c.score)
            )
        })
        .collect();

    let out = format!(r#"{{"order":[{}]}}"#, items.join(","));
    respond(stream, 200, &out)
}
