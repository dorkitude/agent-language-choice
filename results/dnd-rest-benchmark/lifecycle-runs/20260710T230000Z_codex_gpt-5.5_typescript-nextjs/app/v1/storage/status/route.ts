import { json } from "../../../api.js";
import { storageStatus } from "../db.js";

export const runtime = "nodejs";

export function GET() {
  return json(storageStatus());
}
