import { NextResponse } from "next/server";
import { getMonster } from "../../store";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;
  const monster = getMonster(slug);
  if (!monster) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json(monster);
}
