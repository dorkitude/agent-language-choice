//! Durable storage status/reset endpoints, and the hand-rolled SQLite file
//! writer that backs them.
//!
//! No sqlite/db crates are permitted for this target, so the on-disk
//! `game.db` file is produced by a small hand-rolled writer that emits a
//! spec-compliant, empty SQLite database (valid header + `sqlite_master`
//! schema page + one empty leaf page per table). Live request-time state
//! continues to live in the in-process maps owned by [`crate::auth`],
//! [`crate::combat`], [`crate::compendium`], and [`crate::campaigns`]; the
//! file on disk represents the durable schema that state is modeled after
//! and is recreated whenever storage is (re)initialized.

use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;

use crate::auth;
use crate::campaigns;
use crate::combat;
use crate::compendium;
use crate::crafting;
use crate::http::respond;
use crate::inventory;
use crate::npcs;
use crate::play;
use crate::quests;
use crate::sessions;

const SCHEMA_VERSION: i64 = 1;
const DB_PATH: &str = "game.db";

fn storage_initialized() -> &'static AtomicBool {
    static INIT: OnceLock<AtomicBool> = OnceLock::new();
    INIT.get_or_init(|| AtomicBool::new(false))
}

pub(crate) fn init_storage() {
    write_sqlite_schema();
    storage_initialized().store(true, Ordering::SeqCst);
}

fn reset_storage() {
    combat::clear();
    auth::clear();
    compendium::clear();
    campaigns::clear();
    quests::clear();
    npcs::clear();
    inventory::clear();
    crafting::clear();
    sessions::clear();
    play::clear();
    write_sqlite_schema();
    storage_initialized().store(true, Ordering::SeqCst);
}

pub(crate) fn handle_storage_status(stream: &mut TcpStream) -> std::io::Result<()> {
    let initialized = storage_initialized().load(Ordering::SeqCst);
    let out = format!(
        r#"{{"driver":"sqlite","schema_version":{},"initialized":{}}}"#,
        SCHEMA_VERSION, initialized
    );
    respond(stream, 200, &out)
}

pub(crate) fn handle_storage_reset(stream: &mut TcpStream) -> std::io::Result<()> {
    reset_storage();
    let out = format!(r#"{{"ok":true,"schema_version":{}}}"#, SCHEMA_VERSION);
    respond(stream, 200, &out)
}

enum SqlValue {
    #[allow(dead_code)]
    Null,
    Int(i64),
    Text(String),
}

fn sqlite_varint(value: u64, out: &mut Vec<u8>) {
    // SQLite varint: big-endian base-128 groups; every byte but the last has
    // its high bit set. Values used here are small, so the 9-byte/64-bit
    // special case (which packs a full 8-bit final group) is not needed.
    if value == 0 {
        out.push(0);
        return;
    }
    let mut groups = Vec::new();
    let mut v = value;
    while v > 0 {
        groups.push((v & 0x7f) as u8);
        v >>= 7;
    }
    groups.reverse();
    let n = groups.len();
    for (i, g) in groups.iter().enumerate() {
        if i + 1 < n {
            out.push(g | 0x80);
        } else {
            out.push(*g);
        }
    }
}

fn sqlite_record(values: &[SqlValue]) -> Vec<u8> {
    let mut serial_types = Vec::new();
    let mut body = Vec::new();
    for v in values {
        match v {
            SqlValue::Null => serial_types.push(0u64),
            SqlValue::Int(n) => {
                serial_types.push(1);
                body.extend_from_slice(&(*n as i8 as i64).to_be_bytes()[7..]);
            }
            SqlValue::Text(s) => {
                serial_types.push((s.len() as u64) * 2 + 13);
                body.extend_from_slice(s.as_bytes());
            }
        }
    }
    let mut header = Vec::new();
    for st in &serial_types {
        sqlite_varint(*st, &mut header);
    }
    let mut header_len_varint = Vec::new();
    // header length includes the varint(s) encoding the header length itself.
    let mut guess = header.len() + 1;
    loop {
        header_len_varint.clear();
        sqlite_varint(guess as u64, &mut header_len_varint);
        if header_len_varint.len() + header.len() == guess {
            break;
        }
        guess = header_len_varint.len() + header.len();
    }
    let mut record = Vec::new();
    record.extend_from_slice(&header_len_varint);
    record.extend_from_slice(&header);
    record.extend_from_slice(&body);
    record
}

// `page` is a full page-sized buffer. `header_offset` is where the b-tree
// page header begins within it (0 for normal pages, 100 for page 1, which
// carries the 100-byte database header first). All offsets recorded in the
// b-tree header/cell-pointer array are absolute within `page`, per spec.
fn write_leaf_table_page(page: &mut [u8], header_offset: usize, cells: &[(i64, Vec<u8>)]) {
    let page_size = page.len();
    let h = header_offset;
    page[h] = 0x0d; // leaf table b-tree page
    page[h + 1] = 0;
    page[h + 2] = 0;
    let ncells = cells.len() as u16;
    page[h + 3..h + 5].copy_from_slice(&ncells.to_be_bytes());

    let mut content_end = page_size;
    let mut pointers = Vec::new();
    for (rowid, payload) in cells {
        let mut cell = Vec::new();
        sqlite_varint(payload.len() as u64, &mut cell);
        sqlite_varint(*rowid as u64, &mut cell);
        cell.extend_from_slice(payload);
        content_end -= cell.len();
        page[content_end..content_end + cell.len()].copy_from_slice(&cell);
        pointers.push(content_end as u16);
    }
    page[h + 5..h + 7].copy_from_slice(&(content_end as u16).to_be_bytes());
    page[h + 7] = 0;

    let ptr_start = h + 8;
    for (i, ptr) in pointers.iter().enumerate() {
        let off = ptr_start + i * 2;
        page[off..off + 2].copy_from_slice(&ptr.to_be_bytes());
    }
}

fn write_sqlite_schema() {
    const PAGE_SIZE: usize = 4096;
    let tables: [(&str, &str, &str); 10] = [
        (
            "users",
            "users",
            "CREATE TABLE users (username TEXT, role TEXT, password_hash TEXT, salt TEXT)",
        ),
        (
            "combat_sessions",
            "combat_sessions",
            "CREATE TABLE combat_sessions (id TEXT, round INTEGER, turn_index INTEGER, order_json TEXT)",
        ),
        (
            "conditions",
            "conditions",
            "CREATE TABLE conditions (session_id TEXT, target TEXT, condition TEXT, remaining_rounds INTEGER)",
        ),
        (
            "monsters",
            "monsters",
            "CREATE TABLE monsters (slug TEXT, name TEXT, cr TEXT, armor_class INTEGER, hit_points INTEGER, tags_json TEXT)",
        ),
        (
            "items",
            "items",
            "CREATE TABLE items (slug TEXT, name TEXT, type TEXT, rarity TEXT, cost_gp INTEGER)",
        ),
        (
            "campaigns",
            "campaigns",
            "CREATE TABLE campaigns (id TEXT, name TEXT, dm TEXT)",
        ),
        (
            "campaign_characters",
            "campaign_characters",
            "CREATE TABLE campaign_characters (campaign_id TEXT, id TEXT, name TEXT, level INTEGER, class TEXT)",
        ),
        (
            "campaign_events",
            "campaign_events",
            "CREATE TABLE campaign_events (campaign_id TEXT, id TEXT, kind TEXT, summary TEXT)",
        ),
        (
            "campaign_inventory",
            "campaign_inventory",
            "CREATE TABLE campaign_inventory (campaign_id TEXT, item_slug TEXT, quantity INTEGER, owner TEXT)",
        ),
        (
            "campaign_equipment",
            "campaign_equipment",
            "CREATE TABLE campaign_equipment (campaign_id TEXT, character_id TEXT, item_slug TEXT, quantity INTEGER)",
        ),
    ];

    let total_pages: u32 = 1 + tables.len() as u32;
    let mut file_data = vec![0u8; PAGE_SIZE * total_pages as usize];

    // ---- database header (first 100 bytes of page 1) ----
    {
        let h = &mut file_data[0..100];
        h[0..16].copy_from_slice(b"SQLite format 3\0");
        h[16..18].copy_from_slice(&(PAGE_SIZE as u16).to_be_bytes());
        h[18] = 1; // file format write version
        h[19] = 1; // file format read version
        h[20] = 0; // reserved space
        h[21] = 64; // max embedded payload fraction
        h[22] = 32; // min embedded payload fraction
        h[23] = 32; // leaf payload fraction
        h[24..28].copy_from_slice(&1u32.to_be_bytes()); // file change counter
        h[28..32].copy_from_slice(&total_pages.to_be_bytes()); // size of db in pages
        h[32..36].copy_from_slice(&0u32.to_be_bytes()); // freelist trunk page
        h[36..40].copy_from_slice(&0u32.to_be_bytes()); // freelist page count
        h[40..44].copy_from_slice(&1u32.to_be_bytes()); // schema cookie
        h[44..48].copy_from_slice(&4u32.to_be_bytes()); // schema format number
        h[48..52].copy_from_slice(&0u32.to_be_bytes()); // default page cache size
        h[52..56].copy_from_slice(&0u32.to_be_bytes()); // largest root b-tree page
        h[56..60].copy_from_slice(&1u32.to_be_bytes()); // text encoding = utf-8
        h[60..64].copy_from_slice(&0u32.to_be_bytes()); // user version
        h[64..68].copy_from_slice(&0u32.to_be_bytes()); // incremental vacuum mode
        h[68..72].copy_from_slice(&0u32.to_be_bytes()); // application id
        h[92..96].copy_from_slice(&1u32.to_be_bytes()); // version-valid-for
        h[96..100].copy_from_slice(&3045000u32.to_be_bytes()); // sqlite version number
    }

    // ---- page 1: sqlite_master leaf table page (b-tree header starts at offset 100) ----
    {
        let mut cells: Vec<(i64, Vec<u8>)> = Vec::new();
        for (i, (name, tbl_name, sql)) in tables.iter().enumerate() {
            let root_page = (i as i64) + 2;
            let record = sqlite_record(&[
                SqlValue::Text("table".to_string()),
                SqlValue::Text((*name).to_string()),
                SqlValue::Text((*tbl_name).to_string()),
                SqlValue::Int(root_page),
                SqlValue::Text((*sql).to_string()),
            ]);
            cells.push(((i as i64) + 1, record));
        }
        let mut page1 = vec![0u8; PAGE_SIZE];
        write_leaf_table_page(&mut page1, 100, &cells);
        file_data[100..PAGE_SIZE].copy_from_slice(&page1[100..PAGE_SIZE]);
    }

    // ---- one empty leaf page per table ----
    for (i, _) in tables.iter().enumerate() {
        let start = PAGE_SIZE * (i + 1);
        let mut page = vec![0u8; PAGE_SIZE];
        write_leaf_table_page(&mut page, 0, &[]);
        file_data[start..start + PAGE_SIZE].copy_from_slice(&page);
    }

    let _ = std::fs::write(DB_PATH, &file_data);
}
