use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};

/// In-memory combatant used by initiative and combat-session ordering.
///
/// `score` is the initiative total (roll + dexterity). The dexterity score and
/// name are used as deterministic tie-breakers when scores are equal.
#[derive(Clone)]
pub struct Combatant {
    pub name: String,
    pub score: i64,
    pub dex: i64,
}

/// A temporary condition applied to a combatant during a session.
#[derive(Clone)]
pub struct Condition {
    pub name: String,
    pub remaining: i64,
}

/// Mutable runtime state for a single combat encounter.
pub struct CombatSession {
    pub id: String,
    pub round: i64,
    pub turn_index: usize,
    pub order: Vec<Combatant>,
    pub conditions: HashMap<String, Vec<Condition>>,
}

/// Registered user record.
///
/// Only the password hash is stored in memory. The role is used by the
/// dispatcher to enforce DM-only and player-only endpoints.
#[allow(dead_code)]
pub struct User {
    pub username: String,
    pub role: String,
    pub password_hash: String,
}

/// Global runtime cache of combat sessions. Persisted to SQLite on every
/// mutating combat/auth request.
pub static SESSIONS: LazyLock<Mutex<HashMap<String, CombatSession>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// Global runtime cache of registered users. Persisted to SQLite on every
/// mutating auth request.
pub static USERS: LazyLock<Mutex<HashMap<String, User>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));
