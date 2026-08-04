import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { getPlayContent, updatePlayContent } from "../../../../../store.js";

function validateTags(value: unknown): string[] | Response {
  if (!Array.isArray(value)) {
    return Response.json({ error: "tags must be an array of strings" }, { status: 400 });
  }
  const seen = new Set<string>();
  for (const tag of value) {
    if (typeof tag !== "string" || tag.length === 0) {
      return Response.json(
        { error: "tags must be an array of unique non-empty strings" },
        { status: 400 },
      );
    }
    if (seen.has(tag)) {
      return Response.json(
        { error: "tags must be an array of unique non-empty strings" },
        { status: 400 },
      );
    }
    seen.add(tag);
  }
  return value as string[];
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string; content_id: string }> },
) {
  const { id: campaignId, content_id: contentId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may replace content tags",
  );
  if (ownerCheck) return ownerCheck;

  const content = getPlayContent(campaignId, contentId);
  if (!content) {
    return Response.json(
      { error: `content ${contentId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { tags?: unknown };

  const validTags = validateTags(body.tags);
  if (validTags instanceof Response) return validTags;

  const updatedContent = updatePlayContent(campaignId, { ...content, tags: validTags });

  return Response.json(
    {
      content_id: updatedContent.content_id,
      kind: updatedContent.kind,
      text: updatedContent.text,
      tags: updatedContent.tags,
    },
    { status: 200 },
  );
}
