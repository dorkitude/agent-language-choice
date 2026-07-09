"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
/// <reference path="./node-globals.d.ts" />
const fs = __importStar(require("fs"));
function main() {
    let input;
    try {
        input = fs.readFileSync(0, 'utf8');
    }
    catch {
        return;
    }
    const lines = input.split('\n');
    const ops = [];
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (line.trim() === '')
            continue;
        let obj;
        try {
            obj = JSON.parse(line);
        }
        catch {
            continue;
        }
        if (obj === null || typeof obj !== 'object')
            continue;
        if (typeof obj.ts !== 'number' ||
            typeof obj.op !== 'string' ||
            typeof obj.key !== 'string') {
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
        if (a.ts !== b.ts)
            return a.ts < b.ts ? -1 : 1;
        return a.idx - b.idx;
    });
    const map = new Map();
    for (const o of ops) {
        if (o.op === 'set') {
            if (typeof o.value === 'string') {
                map.set(o.key, o.value);
            }
        }
        else if (o.op === 'delete') {
            map.delete(o.key);
        }
    }
    // Sort keys bytewise (UTF-8 byte order = code point order).
    const keys = Array.from(map.keys());
    keys.sort((a, b) => Buffer.from(a, 'utf8').compare(Buffer.from(b, 'utf8')));
    if (keys.length === 0)
        return;
    let out = '';
    for (const k of keys) {
        out += k + '=' + map.get(k) + '\n';
    }
    process.stdout.write(out);
}
main();
