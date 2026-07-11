import { getItem } from "../../../../lib/compendium.js";

function slugFromUrl(url: string): string {
  const segments = new URL(url).pathname.split("/").filter(Boolean);
  return segments[segments.length - 1] ?? "";
}

export async function GET(request: Request) {
  try {
    const slug = slugFromUrl(request.url);
    const item = getItem(slug);
    if (!item) {
      return Response.json({ error: "item not found" }, { status: 404 });
    }
    return Response.json(item);
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    return Response.json({ error: message }, { status: 400 });
  }
}
