import { getDb, storageStatus } from "../../../lib/db.js";

export function GET() {
  getDb();
  return Response.json(storageStatus());
}
