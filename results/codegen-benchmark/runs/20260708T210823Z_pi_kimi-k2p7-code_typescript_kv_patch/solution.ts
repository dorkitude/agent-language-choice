declare const process: { stdout: { write: (data: string) => void } };
declare const require: (id: string) => any;
declare const Buffer: any;

interface Op {
  ts: number;
  op: "set" | "delete";
  key: string;
  value?: string;
}

function main() {
  const fs = require("fs");
  const input: string = fs.readFileSync(0, "utf-8");
  const lines = input.split("\n").filter((line: string) => line.length > 0);

  const records: Op[] = [];
  for (const line of lines) {
    records.push(JSON.parse(line) as Op);
  }

  records.sort((a, b) => a.ts - b.ts);

  const map = new Map<string, string>();
  for (const rec of records) {
    if (rec.op === "set") {
      map.set(rec.key, rec.value ?? "");
    } else if (rec.op === "delete") {
      map.delete(rec.key);
    }
  }

  const keys = Array.from(map.keys()).sort((a, b) =>
    Buffer.compare(Buffer.from(a, "utf8"), Buffer.from(b, "utf8"))
  );
  const output = keys.map((k) => `${k}=${map.get(k)!}`).join("\n");
  if (output.length > 0) {
    process.stdout.write(output + "\n");
  }
}

main();
