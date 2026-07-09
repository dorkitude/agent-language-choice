"use strict";
function main() {
    var _a;
    const fs = require("fs");
    const input = fs.readFileSync(0, "utf-8");
    const lines = input.split("\n").filter((line) => line.length > 0);
    const records = [];
    for (const line of lines) {
        records.push(JSON.parse(line));
    }
    records.sort((a, b) => a.ts - b.ts);
    const map = new Map();
    for (const rec of records) {
        if (rec.op === "set") {
            map.set(rec.key, (_a = rec.value) !== null && _a !== void 0 ? _a : "");
        }
        else if (rec.op === "delete") {
            map.delete(rec.key);
        }
    }
    const keys = Array.from(map.keys()).sort((a, b) => Buffer.compare(Buffer.from(a, "utf8"), Buffer.from(b, "utf8")));
    const output = keys.map((k) => `${k}=${map.get(k)}`).join("\n");
    if (output.length > 0) {
        process.stdout.write(output + "\n");
    }
}
main();
