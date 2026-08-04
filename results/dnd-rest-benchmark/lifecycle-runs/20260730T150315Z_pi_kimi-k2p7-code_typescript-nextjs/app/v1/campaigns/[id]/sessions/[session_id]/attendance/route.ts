import { NextResponse } from "next/server";
import { badRequest, notFound, parseJsonBody } from "../../../../../../lib/http.js";
import { isNonEmptyStringArray } from "../../../../../../lib/validate.js";
import { getCampaign, getSession, recordAttendance } from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; session_id: string }> }
) {
  const { id, session_id } = await params;

  if (!getCampaign(id)) {
    return notFound();
  }

  if (!getSession(id, session_id)) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyStringArray(b.present) || !isNonEmptyStringArray(b.absent)) {
    return badRequest();
  }

  const result = recordAttendance(id, session_id, b.present, b.absent);
  if (!result) {
    return notFound();
  }

  return NextResponse.json(result);
}
