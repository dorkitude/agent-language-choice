import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  calendarWeather,
  createPlayCalendar,
  getPlayCalendar,
  getPlayMemberForUser,
  PlayCalendar,
  PlaySeason,
} from "../../../store.js";

const VALID_SEASONS: PlaySeason[] = ["spring", "summer", "autumn", "winter"];

function serializeCalendar(calendar: PlayCalendar) {
  return {
    day: calendar.day,
    season: calendar.season,
    weather: calendarWeather(calendar.day, calendar.season),
  };
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
    "only the campaign dm may initialize the calendar",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { day?: unknown; season?: unknown };

  const { day, season } = body;
  if (typeof day !== "number" || !Number.isInteger(day) || day < 1) {
    return Response.json({ error: "day must be an integer greater than or equal to 1" }, { status: 400 });
  }
  if (typeof season !== "string" || !VALID_SEASONS.includes(season as PlaySeason)) {
    return Response.json(
      { error: "season must be one of spring, summer, autumn, winter" },
      { status: 400 },
    );
  }

  if (getPlayCalendar(campaignId)) {
    return Response.json(
      { error: `calendar already initialized for campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const calendar = createPlayCalendar({
    campaign_id: campaignId,
    day,
    season: season as PlaySeason,
  });

  return Response.json(serializeCalendar(calendar), { status: 201 });
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

  const calendar = getPlayCalendar(campaignId);
  if (!calendar) {
    return Response.json(
      { error: `calendar not initialized for campaign ${campaignId}` },
      { status: 404 },
    );
  }

  return Response.json(serializeCalendar(calendar), { status: 200 });
}
