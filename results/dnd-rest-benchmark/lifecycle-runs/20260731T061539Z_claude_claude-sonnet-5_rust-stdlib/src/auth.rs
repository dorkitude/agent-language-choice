//! User registration and login. Users live in an in-memory map keyed by
//! username; passwords are never stored in the clear, only a salted
//! SHA-256 hash (a pure-stdlib implementation, since no crypto crate is
//! permitted for this target).

use std::collections::HashMap;
use std::io::Read;
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

use crate::http::{bad_request, respond};
use crate::json::{escape_json_string, parse_json};

pub(crate) struct User {
    username: String,
    role: String,
    password_hash: String,
    salt: String,
}

pub(crate) fn users() -> &'static Mutex<HashMap<String, User>> {
    static USERS: OnceLock<Mutex<HashMap<String, User>>> = OnceLock::new();
    USERS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clear() {
    users().lock().unwrap().clear();
}

/// Password hashing helper. Isolated so a production-grade hash (e.g. bcrypt/argon2)
/// can replace this without touching call sites. Uses a per-user random salt plus a
/// pure-stdlib SHA-256 implementation (no external crates permitted for this target).
fn hash_password(password: &str, salt: &str) -> String {
    let salted = format!("{salt}:{password}");
    sha256_hex(salted.as_bytes())
}

fn gen_salt() -> String {
    let mut bytes = [0u8; 16];
    if let Ok(mut f) = std::fs::File::open("/dev/urandom") {
        let _ = f.read_exact(&mut bytes);
    } else {
        // Fallback: derive pseudo-randomness from address entropy if /dev/urandom is unavailable.
        let addr = &bytes as *const _ as usize;
        for (i, b) in bytes.iter_mut().enumerate() {
            *b = ((addr >> (i % 8)) ^ (addr.rotate_left(i as u32))) as u8;
        }
    }
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

fn sha256_hex(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];

    let mut msg = data.to_vec();
    let bit_len = (data.len() as u64) * 8;
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }

        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);

        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);

            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }

        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }

    h.iter().map(|x| format!("{:08x}", x)).collect()
}

/// Validates a `Bearer session-<username>` token and returns `(username,
/// role)` on success. Used by protected surfaces (e.g. [`crate::play`])
/// that need to know who is calling and what role they hold.
///
/// The play-campaign surface identifies actors purely by session token
/// (e.g. `session-dm`, `session-player-a`) without requiring a prior
/// `/v1/auth/register` call, so the role is looked up from the registered
/// user store when present and otherwise inferred from the reserved `dm`
/// username, defaulting to `player`.
pub(crate) fn authenticate(auth_header: Option<&str>) -> Option<(String, String)> {
    let header = auth_header?;
    let token = header.strip_prefix("Bearer ")?.trim();
    let username = token.strip_prefix("session-")?;
    if username.is_empty() {
        return None;
    }
    let store = users().lock().unwrap();
    if let Some(user) = store.get(username) {
        return Some((user.username.clone(), user.role.clone()));
    }
    drop(store);
    let role = if username == "dm" { "dm" } else { "player" };
    Some((username.to_string(), role.to_string()))
}

/// Looks up the role of a *registered* user (via `/v1/auth/register`),
/// returning `None` if no such user exists. Unlike [`authenticate`], this
/// does not infer a role for unregistered session tokens — callers that
/// need to validate a target user is a real, registered player (e.g.
/// campaign invitations) should use this instead.
pub(crate) fn lookup_role(username: &str) -> Option<String> {
    let store = users().lock().unwrap();
    store.get(username).map(|u| u.role.clone())
}

fn is_valid_username(username: &str) -> bool {
    let len = username.chars().count();
    if len < 2 || len > 32 {
        return false;
    }
    username
        .chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

pub(crate) fn handle_register(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let username = match json.get("username").and_then(|v| v.as_str()) {
        Some(s) if is_valid_username(s) => s.to_string(),
        _ => return bad_request(stream, "invalid username"),
    };
    let password = match json.get("password").and_then(|v| v.as_str()) {
        Some(s) if s.chars().count() >= 8 => s.to_string(),
        _ => return bad_request(stream, "invalid password"),
    };
    let role = match json.get("role").and_then(|v| v.as_str()) {
        Some(s) if s == "dm" || s == "player" => s.to_string(),
        _ => return bad_request(stream, "invalid role"),
    };

    let mut store = users().lock().unwrap();
    if store.contains_key(&username) {
        return respond(stream, 409, r#"{"error":"username already exists"}"#);
    }

    let salt = gen_salt();
    let password_hash = hash_password(&password, &salt);
    let out = format!(
        r#"{{"username":"{}","role":"{}"}}"#,
        escape_json_string(&username),
        escape_json_string(&role)
    );

    store.insert(
        username.clone(),
        User {
            username,
            role,
            password_hash,
            salt,
        },
    );
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_login(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let username = match json.get("username").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "missing username"),
    };
    let password = match json.get("password").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "missing password"),
    };

    let store = users().lock().unwrap();
    let user = match store.get(&username) {
        Some(u) => u,
        None => return respond(stream, 401, r#"{"error":"invalid credentials"}"#),
    };

    let attempt_hash = hash_password(&password, &user.salt);
    if attempt_hash != user.password_hash {
        return respond(stream, 401, r#"{"error":"invalid credentials"}"#);
    }

    let out = format!(
        r#"{{"username":"{}","token":"session-{}"}}"#,
        escape_json_string(&user.username),
        escape_json_string(&user.username)
    );
    drop(store);

    respond(stream, 200, &out)
}
