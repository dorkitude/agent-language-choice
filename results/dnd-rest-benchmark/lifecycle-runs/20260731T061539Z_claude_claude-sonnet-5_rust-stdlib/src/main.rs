//! Entry point: initializes durable storage, binds the HTTP listener on
//! `127.0.0.1:$PORT`, and serves requests one connection at a time. See
//! `CODEBASE.md` for a map of the modules below.

mod analytics;
mod audit;
mod auth;
mod campaigns;
mod characters;
mod combat;
mod compendium;
mod crafting;
mod dice;
mod dm_tools;
mod encounters;
mod http;
mod inventory;
mod json;
mod npcs;
mod play;
mod quests;
mod sessions;
mod storage;

use std::env;
use std::net::TcpListener;

fn main() -> std::io::Result<()> {
    storage::init_storage();
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let listener = TcpListener::bind(format!("127.0.0.1:{port}"))?;
    for stream in listener.incoming() {
        if let Ok(mut stream) = stream {
            let _ = http::handle(&mut stream);
        }
    }
    Ok(())
}
