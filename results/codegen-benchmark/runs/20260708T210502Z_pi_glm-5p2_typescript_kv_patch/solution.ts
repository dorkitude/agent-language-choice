/// <reference path="./node-globals.d.ts" />
import * as fs from 'fs';

interface Op {
  ts: number;
  op: string;
  key: string;
  value?: string;
  idx: number;
}

function main(): void {
  let input: string;
  try {
    input = fs.readFileSync(0, 'utf8');
  } catch {
    return;
  }

  const lines = input.split('\n');
  const ops: Op[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim() === '') continue;
    let obj: any;
    try {
      obj = JSON.parse(line);
    } catch {
      continue;
    }
    if (obj === null || typeof obj !== 'object') continue;
    if (
      typeof obj.ts !== 'number' ||
      typeof obj.op !== 'string' ||
      typeof obj.key !== 'string'
    ) {
      continue;
    }
    ops.push({
      ts: obj.ts,
      op: obj.op,
      key: obj.key,
      value: obj.value,
      idx: i,
    });
  }

  // Stable sort by ts ascending; on ties, preserve input order via idx.
  ops.sort((a, b) => {
    if (a.ts !== b.ts) return a.ts < b.ts ? -1 : 1;
    return a.idx - b.idx;
  });

  const map = new Map<string, string>();
  for (const o of ops) {
    if (o.op === 'set') {
      if (typeof o.value === 'string') {
        map.set(o.key, o.value);
      }
    } else if (o.op === 'delete') {
      map.delete(o.key);
    }
  }

  // Sort keys bytewise (UTF-8 byte order = code point order).
  const keys = Array.from(map.keys());
  keys.sort((a, b) => Buffer.from(a, 'utf8').compare(Buffer.from(b, 'utf8')));

  if (keys.length === 0) return;
  let out = '';
  for (const k of keys) {
    out += k + '=' + map.get(k) + '\n';
  }
  process.stdout.write(out);
}

main();
