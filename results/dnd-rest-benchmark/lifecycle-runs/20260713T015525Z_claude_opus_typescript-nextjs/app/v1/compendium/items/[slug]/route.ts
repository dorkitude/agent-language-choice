import { NextResponse } from "next/server";
import { getItem } from "../../store";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;
  const item = getItem(slug);
  if (!item) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json(item);
}
