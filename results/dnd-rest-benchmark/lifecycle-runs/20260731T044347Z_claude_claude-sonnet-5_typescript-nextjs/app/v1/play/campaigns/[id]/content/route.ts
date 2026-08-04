import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayContent,
  getPlayMemberForUser,
  hasPlayContent,
  listPlayContent,
  PlayContent,
} from "../../../store.js";

function serializeContent(content: PlayContent) {
  return {
    content_id: content.content_id,
    kind: content.kind,
    text: content.text,
    tags: content.tags,
  };
}

function validateTags(value: unknown): string[] | Response {
  if (!Array.isArray(value) || value.length === 0) {
    return Response.json({ error: "tags must be a non-empty array of strings" }, { status: 400 });
  }
  const seen = new Set<string>();
  for (const tag of value) {
    if (typeof tag !== "string" || tag.length === 0) {
      return Response.json(
        { error: "tags must be a non-empty array of unique non-empty strings" },
        { status: 400 },
      );
    }
    if (seen.has(tag)) {
      return Response.json(
        { error: "tags must be a non-empty array of unique non-empty strings" },
        { status: 400 },
      );
    }
    seen.add(tag);
  }
  return value as string[];
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may create content",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    content_id?: unknown;
    kind?: unknown;
    text?: unknown;
    tags?: unknown;
  };

  const validContentId = requireNonEmptyString(body.content_id, "content_id");
  if (validContentId instanceof Response) return validContentId;

  const validKind = requireNonEmptyString(body.kind, "kind");
  if (validKind instanceof Response) return validKind;

  const validText = requireNonEmptyString(body.text, "text");
  if (validText instanceof Response) return validText;

  const validTags = validateTags(body.tags);
  if (validTags instanceof Response) return validTags;

  if (hasPlayContent(campaignId, validContentId)) {
    return Response.json(
      { error: `content ${validContentId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const content: PlayContent = {
    content_id: validContentId,
    kind: validKind,
    text: validText,
    tags: validTags,
  };

  createPlayContent(campaignId, content);

  return Response.json(serializeContent(content), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const member = isDm ? undefined : getPlayMemberForUser(campaignId, username);
  const isMember = isDm || member !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const url = new URL(request.url);
  const excludeTag = url.searchParams.get("exclude_tag");
  if (excludeTag !== null && excludeTag.length === 0) {
    return Response.json({ error: "exclude_tag must be a non-empty string" }, { status: 400 });
  }

  const allContent = listPlayContent(campaignId);
  const visibleContent =
    isDm || excludeTag === null
      ? allContent
      : allContent.filter((content) => !content.tags.includes(excludeTag));

  return Response.json({ content: visibleContent.map(serializeContent) }, { status: 200 });
}
