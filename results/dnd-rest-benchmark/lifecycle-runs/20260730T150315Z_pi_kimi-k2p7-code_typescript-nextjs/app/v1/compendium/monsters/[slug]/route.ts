import { NextResponse } from "next/server";
import { getMonster } from "../../../../lib/storage.js";
import { notFound } from "../../../../lib/http.js";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;

  const monster = getMonster(slug);
  if (!monster) {
    return notFound();
  }

  return NextResponse.json(monster);
}
