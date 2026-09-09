import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import {
  readPlayCampaignSessionZeroSettings,
  updatePlayCampaignSessionZeroSettings,
} from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function roleForActor(actor: string): "dm" | "player" | undefined {
  if (actor === "dm") return "dm";
  if (actor === "player" || actor === "player-a" || actor === "player-b") return "player";
  return userRole(actor);
}

function authenticate(request: Request): { actor: string; role: "dm" | "player" } | NextResponse {
  const actor = actorFromAuthorization(request);
  const role = actor && roleForActor(actor);
  if (!actor || !role) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  return { actor, role };
}

function sessionZeroSettings(value: unknown): { rules: string; tone: string; consent: string[] } | undefined {
  if (!isRecord(value) || !isNonEmptyString(value.rules) || !isNonEmptyString(value.tone) || !Array.isArray(value.consent)) return undefined;
  if (value.consent.length === 0 || !value.consent.every(isNonEmptyString) || new Set(value.consent).size !== value.consent.length) return undefined;
  return { rules: value.rules, tone: value.tone, consent: value.consent };
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const authentication = authenticate(request);
  if (authentication instanceof NextResponse) return authentication;

  const settings = sessionZeroSettings(await jsonBody(request));
  if (!settings) return badRequest();

  const { id } = await params;
  const result = updatePlayCampaignSessionZeroSettings(id, authentication.actor, settings);
  if (result.result === "updated") return NextResponse.json(result.settings);
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign has already started" }, { status: 409 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const authentication = authenticate(request);
  if (authentication instanceof NextResponse) return authentication;

  const { id } = await params;
  const result = readPlayCampaignSessionZeroSettings(id, authentication.actor);
  if (result.result === "found") return NextResponse.json(result.settings);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Session-zero settings not found" }, { status: 404 });
}
