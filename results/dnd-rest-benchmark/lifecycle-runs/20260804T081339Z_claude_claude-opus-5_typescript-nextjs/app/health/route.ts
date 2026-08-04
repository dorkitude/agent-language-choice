import { json } from "../../lib/http";

export const dynamic = "force-dynamic";

export function GET(): Response {
  return json({ ok: true });
}
