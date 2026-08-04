// Backwards-compatibility shim: the persistence layer is now organized under
// src/lib/db/ by domain, but existing handlers still import from './db.js'.

export * from './db/index.js';
