use crate::json::{
    escape_json, extract_bool, extract_int, extract_objects, extract_string, extract_top_array_content,
};
use crate::store::{campaign_exists, sql_escape, sqlite_query};

pub enum AnalyticsError {
    BadRequest,
    NotFound,
}

/// Return a deterministic campaign analytics summary.
///
/// GET /v1/campaigns/{id}/analytics/summary
pub fn analytics_summary(campaign_id: &str) -> Result<String, AnalyticsError> {
    if !campaign_exists(campaign_id).map_err(|_| AnalyticsError::BadRequest)? {
        return Err(AnalyticsError::NotFound);
    }

    let signals = campaign_signals(campaign_id)?;
    let true_count = signals.iter().filter(|&&v| v).count() as i64;
    let readiness_score = (25 + true_count * 15).min(100);

    let open_quests = count_open_quests(campaign_id)?;
    let friendly_npcs = count_friendly_npcs(campaign_id)?;
    let scheduled_sessions = count_scheduled_sessions(campaign_id)?;
    let inventory_items = count_inventory_items(campaign_id)?;

    Ok(format!(
        r#"{{"campaign_id":"{}","readiness_score":{},"open_quests":{},"friendly_npcs":{},"scheduled_sessions":{},"inventory_items":{}}}"#,
        escape_json(campaign_id),
        readiness_score,
        open_quests,
        friendly_npcs,
        scheduled_sessions,
        inventory_items
    ))
}

/// Return a deterministic maintenance risk report.
///
/// POST /v1/campaigns/{id}/analytics/risk-report
pub fn risk_report(campaign_id: &str, body: &str) -> Result<String, AnalyticsError> {
    if !campaign_exists(campaign_id).map_err(|_| AnalyticsError::BadRequest)? {
        return Err(AnalyticsError::NotFound);
    }

    let include_zeroes = extract_bool(body, "include_zeroes").unwrap_or(false);
    let signals = campaign_signals(campaign_id)?;
    let [has_dm, has_characters, has_next_session, has_active_quest] = signals;

    let mut missing = Vec::new();
    if !has_dm {
        missing.push("dm");
    }
    if !has_characters {
        missing.push("characters");
    }
    if !has_next_session {
        missing.push("next_session");
    }
    if !has_active_quest {
        missing.push("active_quest");
    }
    let core_missing = missing.len();

    if include_zeroes {
        if count_open_quests(campaign_id)? == 0 {
            missing.push("open_quests");
        }
        if count_friendly_npcs(campaign_id)? == 0 {
            missing.push("friendly_npcs");
        }
        if count_scheduled_sessions(campaign_id)? == 0 {
            missing.push("scheduled_sessions");
        }
        if count_inventory_items(campaign_id)? == 0 {
            missing.push("inventory_items");
        }
    }

    let risk_level = match core_missing {
        0 => "low",
        1 | 2 => "medium",
        _ => "high",
    };

    let missing_json = missing
        .iter()
        .map(|s| format!(r#""{}""#, s))
        .collect::<Vec<_>>()
        .join(",");

    Ok(format!(
        r#"{{"campaign_id":"{}","risk_level":"{}","missing":[{}],"signals":{{"has_dm":{},"has_characters":{},"has_next_session":{},"has_active_quest":{}}}}}"#,
        escape_json(campaign_id),
        risk_level,
        missing_json,
        bool_json(has_dm),
        bool_json(has_characters),
        bool_json(has_next_session),
        bool_json(has_active_quest)
    ))
}

fn campaign_signals(campaign_id: &str) -> Result<[bool; 4], AnalyticsError> {
    let dm = fetch_dm(campaign_id)?;
    Ok([
        !dm.is_empty(),
        count_characters(campaign_id)? > 0,
        count_scheduled_sessions(campaign_id)? > 0,
        count_active_quests(campaign_id)? > 0,
    ])
}

fn fetch_dm(campaign_id: &str) -> Result<String, AnalyticsError> {
    let sql = format!(
        "SELECT dm FROM campaigns WHERE id = '{}';",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql).map_err(|_| AnalyticsError::BadRequest)?;
    let content = extract_top_array_content(&output).ok_or(AnalyticsError::BadRequest)?;
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err(AnalyticsError::NotFound);
    }
    extract_string(objects[0], "dm")
        .map(|s| s.to_string())
        .ok_or(AnalyticsError::BadRequest)
}

fn count_characters(campaign_id: &str) -> Result<i64, AnalyticsError> {
    count_rows(campaign_id, "characters", "1=1")
}

fn count_active_quests(campaign_id: &str) -> Result<i64, AnalyticsError> {
    count_rows(campaign_id, "quests", "status = 'active'")
}

fn count_open_quests(campaign_id: &str) -> Result<i64, AnalyticsError> {
    count_rows(campaign_id, "quests", "status != 'completed'")
}

fn count_friendly_npcs(campaign_id: &str) -> Result<i64, AnalyticsError> {
    count_rows(campaign_id, "npcs", "disposition > 0")
}

fn count_scheduled_sessions(campaign_id: &str) -> Result<i64, AnalyticsError> {
    count_rows(campaign_id, "campaign_sessions", "1=1")
}

fn count_inventory_items(campaign_id: &str) -> Result<i64, AnalyticsError> {
    let sql = format!(
        "SELECT COUNT(*) AS cnt FROM (SELECT item_slug FROM campaign_inventory WHERE campaign_id = '{}' AND quantity > 0 UNION SELECT item_slug FROM character_equipment WHERE campaign_id = '{}' AND quantity > 0);",
        sql_escape(campaign_id),
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql).map_err(|_| AnalyticsError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok(0);
    }
    extract_int(objects[0], "cnt").ok_or(AnalyticsError::BadRequest)
}

fn count_rows(campaign_id: &str, table: &str, predicate: &str) -> Result<i64, AnalyticsError> {
    let sql = format!(
        "SELECT COUNT(*) AS cnt FROM {} WHERE campaign_id = '{}' AND {};",
        table,
        sql_escape(campaign_id),
        predicate
    );
    let output = sqlite_query(&sql).map_err(|_| AnalyticsError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok(0);
    }
    extract_int(objects[0], "cnt").ok_or(AnalyticsError::BadRequest)
}

fn bool_json(v: bool) -> &'static str {
    if v {
        "true"
    } else {
        "false"
    }
}
