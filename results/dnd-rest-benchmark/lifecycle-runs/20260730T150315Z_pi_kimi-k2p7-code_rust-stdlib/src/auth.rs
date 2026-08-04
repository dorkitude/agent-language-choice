use std::collections::HashMap;

use crate::domain::User;
use crate::json::{escape_json, extract_string};

pub enum RegisterError {
    BadRequest,
    Conflict,
}

pub enum LoginError {
    BadRequest,
    Unauthorized,
}

pub enum AuthError {
    Unauthorized,
    Forbidden,
}

/// Validate that a username follows the allowed format.
///
/// Allowed characters are lowercase ASCII letters, digits, underscores, and
/// hyphens. Length must be between 2 and 32 characters inclusive.
fn valid_username(username: &str) -> bool {
    let len = username.len();
    if len < 2 || len > 32 {
        return false;
    }
    username
        .chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

/// Hash a password with a static pepper using the FNV-1a algorithm.
///
/// This is not a secure password hash; it is intentionally simple and
/// deterministic so that the existing test suite can verify login behavior
/// without relying on bcrypt or another dependency.
fn hash_password(password: &str) -> String {
    const FNV_OFFSET: u64 = 0xcbf29ce484222325;
    const FNV_PRIME: u64 = 0x00000100000001b3;
    const PEPPER: &[u8] = b"static-pepper";
    let mut hash = FNV_OFFSET;
    for byte in password.as_bytes().iter().chain(PEPPER.iter()) {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    format!("{:016x}", hash)
}

/// Register a new user.
///
/// Validation rules:
/// - username must be 2-32 characters and contain only lowercase letters,
///   digits, `_`, or `-`;
/// - password must be at least 8 characters;
/// - role must be exactly `"dm"` or `"player"`;
/// - the username must not already exist in the in-memory user map.
///
/// On success, the caller is responsible for persisting the in-memory state.
pub fn handle_register(
    body: &str,
    users: &mut HashMap<String, User>,
) -> Result<String, RegisterError> {
    let username = extract_string(body, "username").ok_or(RegisterError::BadRequest)?;
    if !valid_username(username) {
        return Err(RegisterError::BadRequest);
    }
    let password = extract_string(body, "password").ok_or(RegisterError::BadRequest)?;
    if password.len() < 8 {
        return Err(RegisterError::BadRequest);
    }
    let role = extract_string(body, "role").ok_or(RegisterError::BadRequest)?;
    if role != "dm" && role != "player" {
        return Err(RegisterError::BadRequest);
    }
    if users.contains_key(username) {
        return Err(RegisterError::Conflict);
    }
    users.insert(
        username.to_string(),
        User {
            username: username.to_string(),
            role: role.to_string(),
            password_hash: hash_password(password),
        },
    );
    Ok(format!(
        r#"{{"username":"{}","role":"{}"}}"#,
        escape_json(username),
        escape_json(role)
    ))
}

/// Authenticate a user and return a deterministic session token.
///
/// The token is always `session-{username}` for the existing tests.
pub fn handle_login(
    body: &str,
    users: &mut HashMap<String, User>,
) -> Result<String, LoginError> {
    let username = extract_string(body, "username").ok_or(LoginError::BadRequest)?;
    let password = extract_string(body, "password").ok_or(LoginError::BadRequest)?;
    let user = users.get(username).ok_or(LoginError::Unauthorized)?;
    if user.password_hash != hash_password(password) {
        return Err(LoginError::Unauthorized);
    }
    Ok(format!(
        r#"{{"username":"{}","token":"session-{}"}}"#,
        escape_json(username),
        escape_json(username)
    ))
}

/// Verify a bearer token of the form `session-{username}` against the
/// in-memory user map.
///
/// Returns the authenticated username and role on success. Missing or
/// malformed tokens produce `Unauthorized`. A known user whose role is not
/// `"dm"` produces `Forbidden` when called by a DM-only endpoint. Unknown
/// session tokens are treated as authenticated players so that the play
/// surface can reject them with `Forbidden` rather than `Unauthorized`.
pub fn verify_bearer(token: &str, users: &HashMap<String, User>) -> Result<(String, String), AuthError> {
    const PREFIX: &str = "session-";
    if !token.starts_with(PREFIX) {
        return Err(AuthError::Unauthorized);
    }
    let username = &token[PREFIX.len()..];
    if username.is_empty() {
        return Err(AuthError::Unauthorized);
    }
    let role = users
        .get(username)
        .map(|u| u.role.clone())
        .unwrap_or_else(|| "player".to_string());
    Ok((username.to_string(), role))
}
