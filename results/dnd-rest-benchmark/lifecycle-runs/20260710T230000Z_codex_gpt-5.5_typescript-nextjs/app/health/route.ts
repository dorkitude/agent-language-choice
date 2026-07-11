import { json } from "../api.js";

export function GET() {
  return json({ ok: true });
}
