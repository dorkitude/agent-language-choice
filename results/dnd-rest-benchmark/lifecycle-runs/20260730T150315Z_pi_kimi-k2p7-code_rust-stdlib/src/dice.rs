use crate::json::{extract_int, extract_string};

/// Parse a dice expression of the form `NdS` or `NdS+M` / `NdS-M`.
///
/// Returns `(count, sides, modifier)`. `count` and `sides` must be positive.
fn parse_dice_expression(expr: &str) -> Option<(i64, i64, i64)> {
    let expr = expr.trim();
    let d_pos = expr.find('d')?;
    let count = expr[..d_pos].parse::<i64>().ok()?;
    if count <= 0 {
        return None;
    }
    let rest = &expr[d_pos + 1..];
    let mod_pos = rest.find(|c| c == '+' || c == '-');
    let (sides_str, mod_str) = match mod_pos {
        Some(p) => (&rest[..p], &rest[p..]),
        None => (rest, ""),
    };
    let sides = sides_str.parse::<i64>().ok()?;
    if sides <= 0 {
        return None;
    }
    let modifier = if mod_str.is_empty() {
        0
    } else {
        mod_str.parse::<i64>().ok()?
    };
    Some((count, sides, modifier))
}

/// Return statistics for a dice expression without rolling.
///
/// `min` is `count + modifier`, `max` is `count * sides + modifier`, and
/// `average` is the exact mean of the uniform distribution. Averages with a
/// fractional half are rendered as `N.5`.
pub fn handle_dice_stats(body: &str) -> Option<String> {
    let expr = extract_string(body, "expression")?;
    let (count, sides, modifier) = parse_dice_expression(expr)?;
    let min = count + modifier;
    let max = count * sides + modifier;
    let average2 = count * (sides + 1) + 2 * modifier;
    let average = if average2 % 2 == 0 {
        format!("{}", average2 / 2)
    } else {
        format!("{}.5", average2 / 2)
    };
    Some(format!(
        r#"{{"dice_count":{},"sides":{},"modifier":{},"min":{},"max":{},"average":{}}}"#,
        count, sides, modifier, min, max, average
    ))
}

/// Resolve an ability check against a DC.
///
/// Returns the total, success/failure, and the margin (total - dc).
pub fn handle_ability_check(body: &str) -> Option<String> {
    let roll = extract_int(body, "roll")?;
    let modifier = extract_int(body, "modifier")?;
    let dc = extract_int(body, "dc")?;
    let total = roll + modifier;
    let success = total >= dc;
    let margin = total - dc;
    Some(format!(
        r#"{{"total":{},"success":{},"margin":{}}}"#,
        total, success, margin
    ))
}
