import { getItem } from "../../../../../lib/compendium";
import { json, notFound } from "../../../../../lib/http";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ slug: string }> },
): Promise<Response> {
  const { slug } = await context.params;
  const item = getItem(slug);
  if (!item) return notFound("unknown item");
  return json(item);
}
