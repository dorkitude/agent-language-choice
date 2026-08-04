import { ok } from "../lib/http.js";

export async function GET() {
  return ok({ ok: true });
}
