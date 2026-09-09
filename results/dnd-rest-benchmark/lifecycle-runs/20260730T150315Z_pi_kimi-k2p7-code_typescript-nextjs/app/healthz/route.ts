import { ok } from "../lib/http.js";

export const dynamic = "force-dynamic";

export async function GET() {
  return ok({ status: "ok" });
}
