use std::io::{Read, Write};
use std::net::TcpStream;

/// Read a single HTTP/1.1 request from the stream, including its body.
///
/// Reads until the header terminator is found, then continues reading until the
/// body indicated by `Content-Length` is fully received. If no terminator is
/// found, returns whatever was read before the connection closed.
pub fn read_request(stream: &mut TcpStream) -> std::io::Result<String> {
    let mut buf = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        let n = stream.read(&mut chunk)?;
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&chunk[..n]);
        if let Some(pos) = find_subseq(&buf, b"\r\n\r\n") {
            let header_len = pos + 4;
            let content_length = parse_content_length(&buf[..header_len]);
            let total = header_len + content_length;
            if buf.len() >= total {
                buf.truncate(total);
                break;
            }
        }
    }
    Ok(String::from_utf8_lossy(&buf).to_string())
}

/// Locate a byte subsequence inside a byte slice.
fn find_subseq(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

/// Parse the `Content-Length` header from a raw header block.
fn parse_content_length(headers: &[u8]) -> usize {
    let text = String::from_utf8_lossy(headers);
    for line in text.lines() {
        if line.to_lowercase().starts_with("content-length:") {
            if let Some(val) = line.split(':').nth(1) {
                return val.trim().parse().unwrap_or(0);
            }
        }
    }
    0
}

/// Write a JSON HTTP/1.1 response and flush the stream.
///
/// The response includes `Connection: close` so the client knows the server
/// will close the connection when the stream is dropped by the caller.
pub fn respond(stream: &mut TcpStream, status: u16, body: &str) -> std::io::Result<()> {
    let label = match status {
        200 => "OK",
        201 => "Created",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        409 => "Conflict",
        500 => "Internal Server Error",
        _ => "Error",
    };
    write!(
        stream,
        "HTTP/1.1 {status} {label}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    )?;
    stream.flush()
}
