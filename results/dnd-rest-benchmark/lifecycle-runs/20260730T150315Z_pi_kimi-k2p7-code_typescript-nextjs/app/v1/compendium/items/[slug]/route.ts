import { NextResponse } from "next/server";
import { getItem } from "../../../../lib/storage.js";
import { notFound } from "../../../../lib/http.js";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;

  const item = getItem(slug);
  if (!item) {
    return notFound();
  }

  return NextResponse.json(item);
}
