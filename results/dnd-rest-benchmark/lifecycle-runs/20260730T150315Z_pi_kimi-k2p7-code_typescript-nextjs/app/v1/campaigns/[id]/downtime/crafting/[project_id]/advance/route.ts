import { NextResponse } from "next/server";
import { badRequest, notFound, parseJsonBody } from "../../../../../../../lib/http.js";
import { isPositiveInteger } from "../../../../../../../lib/validate.js";
import { advanceCraftingProject } from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; project_id: string }> }
) {
  const { id, project_id } = await params;

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isPositiveInteger(b.days)) {
    return badRequest();
  }

  const result = advanceCraftingProject(id, project_id, b.days);
  if (!result) {
    return notFound();
  }

  return NextResponse.json(result);
}
