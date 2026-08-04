// Protected campaign-play surface. Requests must carry
// `Authorization: Bearer session-<username>` (mirrors the placeholder token
// scheme from routes/auth.ts — no real session store or expiry). 401 for
// missing/invalid credentials, 403 for a valid, known actor lacking
// permission for the action.
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt } from "../validation.js";
import { abilityModifier, proficiencyBonus } from "../domain/rules.js";
import { isMaintenanceMode, setMaintenanceMode } from "../serviceMode.js";

interface Actor {
  username: string;
  role: "dm" | "player";
}

const SESSION_USERNAME_RE = /^[a-z0-9_-]+$/;

// A storage reset clears the users table, but the protected play surface
// must stay usable afterward: usernames are well-formed session identifiers
// on their own, so unknown ones fall back to a default role ('dm' for the
// literal 'dm' username, 'player' otherwise) instead of failing auth.
export function resolveActor(authHeader: string | undefined): Actor | undefined {
  if (!authHeader || !authHeader.startsWith("Bearer ")) return undefined;
  const token = authHeader.slice("Bearer ".length);
  const match = /^session-(.+)$/.exec(token);
  if (!match) return undefined;
  const username = match[1];
  if (!SESSION_USERNAME_RE.test(username)) return undefined;
  const row = db.prepare("SELECT username, role FROM users WHERE username = ?").get(username) as
    | { username: string; role: "dm" | "player" }
    | undefined;
  if (row) return { username: row.username, role: row.role };
  return { username, role: username === "dm" ? "dm" : "player" };
}

// Every protected handler below starts by resolving the caller and bailing
// out with 401 on failure; this shared check keeps that boilerplate in one
// place. Returns `undefined` (after writing the 401 response) when the
// caller should stop handling the request.
function requireActor(res: ServerResponse, authHeader: string | undefined): Actor | undefined {
  const actor = resolveActor(authHeader);
  if (!actor) {
    sendJson(res, 401, { error: "unauthorized" });
    return undefined;
  }
  return actor;
}

// Many DM-only endpoints (scenes, locations, encounters, etc.) share this
// exact "only the campaign owner may do this" check. Writes the 403 response
// and returns false when the caller should stop handling the request.
function requireCampaignOwner(res: ServerResponse, actor: Actor, owner: string): boolean {
  if (actor.username !== owner) {
    sendJson(res, 403, { error: "forbidden" });
    return false;
  }
  return true;
}

// Read-oriented endpoints (turn state, documents, travel, encounter status)
// allow either the owner or any joined member. Writes the 403 response and
// returns false when the caller should stop handling the request.
function requireCampaignOwnerOrMember(res: ServerResponse, campaignId: string, actor: Actor, owner: string): boolean {
  if (actor.username !== owner && !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return false;
  }
  return true;
}

// Slugs shared by every play-campaign sub-resource id (campaign, scene,
// location, encounter): lowercase alphanumeric segments joined by single
// hyphens, matching the compendium slug pattern in CODEBASE.md.
const PLAY_CAMPAIGN_ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function hasPlayCampaign(id: string): boolean {
  const row = db.prepare("SELECT 1 FROM play_campaigns WHERE id = ?").get(id);
  return row !== undefined;
}

interface PlayCampaignRow {
  id: string;
  max_players: number;
}

function getPlayCampaign(id: string): PlayCampaignRow | undefined {
  return db.prepare("SELECT id, max_players FROM play_campaigns WHERE id = ?").get(id) as
    | PlayCampaignRow
    | undefined;
}

interface PlayCampaignOwnerStatusRow {
  owner: string;
  status: string;
}

function getPlayCampaignOwnerStatus(id: string): PlayCampaignOwnerStatusRow | undefined {
  return db.prepare("SELECT owner, status FROM play_campaigns WHERE id = ?").get(id) as
    | PlayCampaignOwnerStatusRow
    | undefined;
}

interface PlayCampaignTurnRow {
  owner: string;
  current_actor: string | null;
  turn_number: number | null;
  turn_deadline: number | null;
  turn_nudge_count: number;
  current_location_id: string | null;
  turn_phase: string | null;
}

function getPlayCampaignTurn(id: string): PlayCampaignTurnRow | undefined {
  return db
    .prepare(
      "SELECT owner, current_actor, turn_number, turn_deadline, turn_nudge_count, current_location_id, turn_phase FROM play_campaigns WHERE id = ?",
    )
    .get(id) as PlayCampaignTurnRow | undefined;
}

// Timeout bookkeeping is purely logical (turn-count based), never wall-clock:
// each fresh turn gets a deadline a fixed number of logical turns out, and
// resets its nudge count to 0 so a brand-new turn is never reported overdue.
const TURN_DEADLINE_WINDOW = 1;

function resetPlayCampaignTurnTimeout(campaignId: string, turnNumber: number): number {
  const deadline = turnNumber + TURN_DEADLINE_WINDOW;
  db.prepare("UPDATE play_campaigns SET turn_deadline = ?, turn_nudge_count = 0 WHERE id = ?").run(
    deadline,
    campaignId,
  );
  return deadline;
}

// Shared by the exploration-turn actions (travel, rest) that only the
// current player-on-turn may take: the DM never "takes a turn" this way
// (409, not a permission problem), a non-member/non-player is a 403, and an
// out-of-turn player is a 409. Returns false after writing the appropriate
// response when the caller should stop handling the request.
function requireCurrentPlayerTurn(
  res: ServerResponse,
  campaignId: string,
  actor: Actor,
  currentActor: string | null,
): boolean {
  if (actor.role === "dm") {
    sendJson(res, 409, { error: "not your turn" });
    return false;
  }
  if (actor.role !== "player" || !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return false;
  }
  if (currentActor !== actor.username) {
    sendJson(res, 409, { error: "not your turn" });
    return false;
  }
  return true;
}

function firstPlayCampaignMemberUsername(campaignId: string): string | undefined {
  const row = db
    .prepare("SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC LIMIT 1")
    .get(campaignId) as { username: string } | undefined;
  return row?.username;
}

function playCampaignMemberUsernamesInJoinOrder(campaignId: string): string[] {
  const rows = db
    .prepare("SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC")
    .all(campaignId) as { username: string }[];
  return rows.map((row) => row.username);
}

// The turn queue interleaves each player (in join order) with a DM turn
// following it: [player-a, dm, player-b, dm, ...].
function buildPlayCampaignTurnQueue(campaignId: string, owner: string): string[] {
  const members = playCampaignMemberUsernamesInJoinOrder(campaignId);
  const queue: string[] = [];
  for (const member of members) {
    queue.push(member);
    queue.push(owner);
  }
  return queue;
}

function hasPlayCampaignMember(campaignId: string, username: string): boolean {
  const row = db
    .prepare("SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?")
    .get(campaignId, username);
  return row !== undefined;
}

function hasPlayCampaignCharacter(campaignId: string, characterId: string): boolean {
  const row = db
    .prepare("SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?")
    .get(campaignId, characterId);
  return row !== undefined;
}

function countPlayCampaignMembers(campaignId: string): number {
  const row = db
    .prepare("SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  return row.count;
}

// --- Campaign lifecycle: create / join / start -----------------------------

export function handleCreatePlayCampaign(res: ServerResponse, authHeader: string | undefined, body: unknown): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;
  if (actor.role !== "dm") {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    typeof body.name !== "string" ||
    !PLAY_CAMPAIGN_ID_RE.test(body.id) ||
    body.name.length === 0 ||
    !isValidInt(body.max_players, 1, 20)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasPlayCampaign(body.id)) {
    sendJson(res, 409, { error: "campaign already exists" });
    return;
  }

  db.prepare("INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)").run(
    body.id,
    body.name,
    actor.username,
    "lobby",
    body.max_players,
  );

  sendJson(res, 201, {
    id: body.id,
    name: body.name,
    owner: actor.username,
    status: "lobby",
    max_players: body.max_players,
  });
}

export function handleJoinPlayCampaign(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;
  if (actor.role !== "player") {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.character_id !== "string" ||
    !body.character_id ||
    typeof body.name !== "string" ||
    !body.name ||
    typeof body.class !== "string" ||
    !body.class
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (
    hasPlayCampaignMember(campaignId, actor.username) ||
    hasPlayCampaignCharacter(campaignId, body.character_id) ||
    countPlayCampaignMembers(campaignId) >= campaign.max_players
  ) {
    sendJson(res, 409, { error: "cannot join campaign" });
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, actor.username, body.character_id, body.name, body.class, actor.username);

  sendJson(res, 201, {
    username: actor.username,
    character_id: body.character_id,
    name: body.name,
    class: body.class,
  });
}

export function handleStartPlayCampaign(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (actor.role !== "dm" || actor.username !== campaign.owner) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (campaign.status !== "lobby" || countPlayCampaignMembers(campaignId) < 2) {
    sendJson(res, 409, { error: "cannot start campaign" });
    return;
  }

  const currentActor = firstPlayCampaignMemberUsername(campaignId) as string;
  db.prepare(
    "UPDATE play_campaigns SET status = 'active', current_actor = ?, turn_number = 1, turn_phase = 'player' WHERE id = ?",
  ).run(currentActor, campaignId);
  resetPlayCampaignTurnTimeout(campaignId, 1);

  sendJson(res, 200, {
    id: campaignId,
    status: "active",
    current_actor: currentActor,
    turn_number: 1,
  });
}

// --- Narration / turn state / player actions / GM resolutions ---------------

function nextPlayCampaignEventSequence(campaignId: string): number {
  const row = db
    .prepare("SELECT MAX(sequence) AS max_sequence FROM play_campaign_events WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number | null };
  return (row.max_sequence ?? 0) + 1;
}

// Appends a narration/action/resolution event and returns the sequence
// number it was assigned, so callers can echo it straight into the response.
function insertPlayCampaignEvent(campaignId: string, kind: string, actor: string, text: string): number {
  const sequence = nextPlayCampaignEventSequence(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, sequence, kind, actor, text);
  return sequence;
}

export function handleAddPlayNarration(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  if (!hasPlayCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (actor.role !== "dm" && !hasActivePlayDelegation(campaignId, actor.username, "narrate")) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!isPlainObject(body) || typeof body.text !== "string" || body.text.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const sequence = insertPlayCampaignEvent(campaignId, "narration", actor.username, body.text);

  sendJson(res, 201, {
    sequence,
    kind: "narration",
    actor: actor.username,
    text: body.text,
  });
}

// Party chat: any campaign member (including the DM) may post an in-character
// or out-of-character message. Stored as a "chat" campaign event; the
// spectator projection never surfaces these.
export function handleAddPlayMessage(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (!isPlainObject(body) || typeof body.text !== "string" || body.text.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const sequence = insertPlayCampaignEvent(campaignId, "chat", actor.username, body.text);

  sendJson(res, 201, {
    sequence,
    kind: "chat",
    actor: actor.username,
    text: body.text,
  });
}

interface PlayCampaignMemberCharacterRow {
  character_id: string;
  name: string;
}

function getPlayCampaignMemberCharacter(
  campaignId: string,
  username: string,
): PlayCampaignMemberCharacterRow | undefined {
  return db
    .prepare("SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?")
    .get(campaignId, username) as PlayCampaignMemberCharacterRow | undefined;
}

interface PlayCampaignMemberSummaryRow {
  username: string;
  character_id: string;
  name: string;
  class: string;
}

function playCampaignMemberSummaries(campaignId: string): PlayCampaignMemberSummaryRow[] {
  return db
    .prepare(
      "SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC",
    )
    .all(campaignId) as unknown as PlayCampaignMemberSummaryRow[];
}

interface PlayCampaignEventRow {
  sequence: number;
  kind: string;
  actor: string;
  text: string;
  destination_id: string | null;
  travel_turns: number | null;
}

const RECENT_EVENTS_LIMIT = 10;

function recentPlayCampaignEvents(campaignId: string): unknown[] {
  const rows = db
    .prepare(
      "SELECT sequence, kind, actor, text, destination_id, travel_turns FROM play_campaign_events WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?",
    )
    .all(campaignId, RECENT_EVENTS_LIMIT) as unknown as PlayCampaignEventRow[];
  return rows.reverse().map((row) => {
    if (row.kind === "travel") {
      return {
        sequence: row.sequence,
        kind: row.kind,
        actor: row.actor,
        destination_id: row.destination_id,
        travel_turns: row.travel_turns,
      };
    }
    return { sequence: row.sequence, kind: row.kind, actor: row.actor, text: row.text };
  });
}

export function handleGetMyTurnContext(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (actor.role !== "player") {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const character = getPlayCampaignMemberCharacter(campaignId, actor.username);
  if (!character) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  sendJson(res, 200, {
    campaign_id: campaignId,
    is_my_turn: campaign.current_actor === actor.username,
    current_actor: campaign.current_actor,
    character: { id: character.character_id, name: character.name },
    recent_events: recentPlayCampaignEvents(campaignId),
  });
}

export function handleGetPlayTurn(res: ServerResponse, authHeader: string | undefined, campaignId: string): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const phase = campaign.turn_phase ?? (campaign.current_actor === campaign.owner ? "dm" : "player");
  const queue = buildPlayCampaignTurnQueue(campaignId, campaign.owner);
  sendJson(res, 200, {
    campaign_id: campaignId,
    current_actor: campaign.current_actor,
    phase,
    turn_number: campaign.turn_number,
    queue,
    overdue: campaign.turn_nudge_count > 0,
    logical_deadline: campaign.turn_deadline,
  });
}

export function handleNudgePlayTurn(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isPlainObject(body) || typeof body.message !== "string" || body.message.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const nudgeCount = campaign.turn_nudge_count + 1;
  db.prepare("UPDATE play_campaigns SET turn_nudge_count = ? WHERE id = ?").run(nudgeCount, campaignId);
  insertPlayCampaignEvent(campaignId, "nudge", actor.username, body.message);

  sendJson(res, 201, {
    actor: actor.username,
    current_actor: campaign.current_actor,
    target: campaign.current_actor,
    message: body.message,
    nudge_count: nudgeCount,
  });
}

export function handleSubmitPlayerAction(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isMember = actor.role === "player" && hasPlayCampaignMember(campaignId, actor.username);
  if (!isMember && actor.username !== campaign.owner) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (actor.role !== "player" || campaign.current_actor !== actor.username) {
    sendJson(res, 409, { error: "not your turn" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.type !== "string" ||
    body.type.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const sequence = insertPlayCampaignEvent(campaignId, "action", actor.username, body.text);

  db.prepare("UPDATE play_campaigns SET current_actor = ?, turn_phase = 'dm' WHERE id = ?").run(
    campaign.owner,
    campaignId,
  );
  resetPlayCampaignTurnTimeout(campaignId, campaign.turn_number ?? 1);

  sendJson(res, 201, {
    sequence,
    kind: "action",
    actor: actor.username,
    type: body.type,
    text: body.text,
    next_actor: "dm",
  });
}

function nextPlayCampaignTurnMember(campaignId: string, owner: string): string {
  const members = playCampaignMemberUsernamesInJoinOrder(campaignId);
  const lastActionRow = db
    .prepare(
      "SELECT actor FROM play_campaign_events WHERE campaign_id = ? AND kind IN ('action', 'travel') ORDER BY sequence DESC LIMIT 1",
    )
    .get(campaignId) as { actor: string } | undefined;
  if (!lastActionRow) return members[0];
  const index = members.indexOf(lastActionRow.actor);
  if (index === -1) return members[0];
  return members[(index + 1) % members.length];
}

export function handleAddResolution(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!isOwner || campaign.current_actor !== campaign.owner) {
    sendJson(res, 409, { error: "not gm turn" });
    return;
  }

  if (!isPlainObject(body) || typeof body.text !== "string" || body.text.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const sequence = insertPlayCampaignEvent(campaignId, "resolution", actor.username, body.text);

  const nextActor = nextPlayCampaignTurnMember(campaignId, campaign.owner);
  const nextTurnNumber = (campaign.turn_number ?? 0) + 1;
  db.prepare("UPDATE play_campaigns SET current_actor = ?, turn_number = ?, turn_phase = 'player' WHERE id = ?").run(
    nextActor,
    nextTurnNumber,
    campaignId,
  );
  resetPlayCampaignTurnTimeout(campaignId, nextTurnNumber);

  sendJson(res, 201, {
    sequence,
    kind: "resolution",
    actor: actor.username,
    text: body.text,
    next_actor: nextActor,
    turn_number: nextTurnNumber,
  });
}

interface PlayCampaignDocumentRow {
  owner: string;
  doc_story: string;
  doc_dm_notes: string;
}

// --- Shared story document (player-visible) / DM notes (owner-only) --------

function getPlayCampaignDocument(id: string): PlayCampaignDocumentRow | undefined {
  return db.prepare("SELECT owner, doc_story, doc_dm_notes FROM play_campaigns WHERE id = ?").get(id) as
    | PlayCampaignDocumentRow
    | undefined;
}

export function handleGetPlayCampaignDocument(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignDocument(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (isOwner) {
    sendJson(res, 200, { story: campaign.doc_story, dm_notes: campaign.doc_dm_notes });
    return;
  }

  sendJson(res, 200, { story: campaign.doc_story });
}

export function handlePutPlayCampaignDocument(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignDocument(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isPlainObject(body) || typeof body.story !== "string" || typeof body.dm_notes !== "string") {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  db.prepare("UPDATE play_campaigns SET doc_story = ?, doc_dm_notes = ? WHERE id = ?").run(
    body.story,
    body.dm_notes,
    campaignId,
  );

  sendJson(res, 200, { story: body.story, dm_notes: body.dm_notes });
}

interface PlayCampaignSceneRow {
  id: string;
  name: string;
  status: string;
}

// --- Scenes: DM-authored exploration checkpoints ----------------------------

function getPlayCampaignScene(campaignId: string, sceneId: string): PlayCampaignSceneRow | undefined {
  return db
    .prepare("SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?")
    .get(campaignId, sceneId) as PlayCampaignSceneRow | undefined;
}

interface PlayCampaignOwnerRow {
  owner: string;
}

function getPlayCampaignOwner(id: string): PlayCampaignOwnerRow | undefined {
  return db.prepare("SELECT owner FROM play_campaigns WHERE id = ?").get(id) as
    | PlayCampaignOwnerRow
    | undefined;
}

export function handleCreatePlayScene(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    typeof body.name !== "string" ||
    !PLAY_CAMPAIGN_ID_RE.test(body.id) ||
    body.name.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayCampaignScene(campaignId, body.id)) {
    sendJson(res, 409, { error: "scene already exists" });
    return;
  }

  db.prepare("INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)").run(
    campaignId,
    body.id,
    body.name,
    "open",
  );

  sendJson(res, 201, { id: body.id, name: body.name, status: "open" });
}

export function handleEnterPlayScene(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  sceneId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const scene = getPlayCampaignScene(campaignId, sceneId);
  if (!scene) {
    sendJson(res, 404, { error: "scene not found" });
    return;
  }

  if (scene.status !== "open") {
    sendJson(res, 409, { error: "scene is closed" });
    return;
  }

  db.prepare("UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?").run(sceneId, campaignId);
  insertPlayCampaignEvent(campaignId, "scene", actor.username, sceneId);

  sendJson(res, 200, { current_scene_id: sceneId, name: scene.name });
}

export function handleClosePlayScene(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  sceneId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const scene = getPlayCampaignScene(campaignId, sceneId);
  if (!scene) {
    sendJson(res, 404, { error: "scene not found" });
    return;
  }

  db.prepare("UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?").run(
    campaignId,
    sceneId,
  );

  sendJson(res, 200, { id: sceneId, status: "closed" });
}

export function handleGetCurrentPlayScene(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const row = db.prepare("SELECT current_scene_id FROM play_campaigns WHERE id = ?").get(campaignId) as
    | { current_scene_id: string | null }
    | undefined;
  const currentSceneId = row?.current_scene_id;
  if (!currentSceneId) {
    sendJson(res, 404, { error: "no current scene" });
    return;
  }

  const scene = getPlayCampaignScene(campaignId, currentSceneId);
  if (!scene || scene.status !== "open") {
    sendJson(res, 404, { error: "no current scene" });
    return;
  }

  sendJson(res, 200, { id: scene.id, name: scene.name, status: scene.status });
}

interface PlayCampaignLocationRow {
  id: string;
  name: string;
}

// --- Locations, connections, and exploration travel -------------------------

function getPlayCampaignLocation(campaignId: string, locationId: string): PlayCampaignLocationRow | undefined {
  return db
    .prepare("SELECT id, name FROM play_campaign_locations WHERE campaign_id = ? AND id = ?")
    .get(campaignId, locationId) as PlayCampaignLocationRow | undefined;
}

function hasPlayCampaignConnection(campaignId: string, fromId: string, toId: string): boolean {
  const row = db
    .prepare(
      "SELECT 1 FROM play_campaign_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
    )
    .get(campaignId, fromId, toId);
  return row !== undefined;
}

function getPlayCampaignConnection(
  campaignId: string,
  fromId: string,
  toId: string,
): { travel_turns: number } | undefined {
  return db
    .prepare(
      "SELECT travel_turns FROM play_campaign_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
    )
    .get(campaignId, fromId, toId) as { travel_turns: number } | undefined;
}

interface PlayCampaignDestinationRow {
  id: string;
  name: string;
  travel_turns: number;
}

function playCampaignDestinations(campaignId: string, fromId: string): PlayCampaignDestinationRow[] {
  return db
    .prepare(
      `SELECT l.id AS id, l.name AS name, c.travel_turns AS travel_turns
       FROM play_campaign_connections c
       JOIN play_campaign_locations l ON l.campaign_id = c.campaign_id AND l.id = c.to_id
       WHERE c.campaign_id = ? AND c.from_id = ?
       ORDER BY l.id ASC`,
    )
    .all(campaignId, fromId) as unknown as PlayCampaignDestinationRow[];
}

export function handleCreatePlayLocation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    typeof body.name !== "string" ||
    !PLAY_CAMPAIGN_ID_RE.test(body.id) ||
    body.name.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayCampaignLocation(campaignId, body.id)) {
    sendJson(res, 409, { error: "location already exists" });
    return;
  }

  db.prepare("INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)").run(
    campaignId,
    body.id,
    body.name,
  );
  db.prepare(
    "UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL",
  ).run(body.id, campaignId);

  sendJson(res, 201, { id: body.id, name: body.name });
}

export function handleCreatePlayConnection(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  fromId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.to_id !== "string" ||
    body.to_id.length === 0 ||
    !isValidInt(body.travel_turns, 1, 1000)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (
    !getPlayCampaignLocation(campaignId, fromId) ||
    !getPlayCampaignLocation(campaignId, body.to_id) ||
    hasPlayCampaignConnection(campaignId, fromId, body.to_id)
  ) {
    sendJson(res, 400, { error: "invalid connection" });
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)",
  ).run(campaignId, fromId, body.to_id, body.travel_turns);

  sendJson(res, 201, { from_id: fromId, to_id: body.to_id, travel_turns: body.travel_turns });
}

export function handleGetPlayLocationTravel(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  locationId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  sendJson(res, 200, { destinations: playCampaignDestinations(campaignId, locationId) });
}

function insertPlayCampaignTravelEvent(
  campaignId: string,
  actor: string,
  destinationId: string,
  travelTurns: number,
): number {
  const sequence = nextPlayCampaignEventSequence(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, destination_id, travel_turns) VALUES (?, ?, 'travel', ?, '', ?, ?)",
  ).run(campaignId, sequence, actor, destinationId, travelTurns);
  return sequence;
}

export function handleTravelPlayCampaignTurn(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCurrentPlayerTurn(res, campaignId, actor, campaign.current_actor)) return;

  if (!isPlainObject(body) || typeof body.destination_id !== "string" || body.destination_id.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const connection =
    campaign.current_location_id !== null
      ? getPlayCampaignConnection(campaignId, campaign.current_location_id, body.destination_id)
      : undefined;
  if (!connection) {
    sendJson(res, 409, { error: "invalid destination" });
    return;
  }

  const sequence = insertPlayCampaignTravelEvent(
    campaignId,
    actor.username,
    body.destination_id,
    connection.travel_turns,
  );

  db.prepare("UPDATE play_campaigns SET current_actor = ?, current_location_id = ? WHERE id = ?").run(
    campaign.owner,
    body.destination_id,
    campaignId,
  );

  sendJson(res, 201, {
    sequence,
    kind: "travel",
    actor: actor.username,
    destination_id: body.destination_id,
    travel_turns: connection.travel_turns,
    next_actor: "dm",
  });
}

interface PlayCampaignMemberHpRow {
  hp_current: number;
  hp_max: number;
}

// --- Short/long rest (exploration turn action) ------------------------------

function getPlayCampaignMemberHp(campaignId: string, username: string): PlayCampaignMemberHpRow | undefined {
  return db
    .prepare("SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?")
    .get(campaignId, username) as PlayCampaignMemberHpRow | undefined;
}

const REST_TYPES = new Set(["short", "long"]);

export function handleRestPlayCampaignTurn(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCurrentPlayerTurn(res, campaignId, actor, campaign.current_actor)) return;

  if (!isPlainObject(body) || typeof body.type !== "string" || !REST_TYPES.has(body.type)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const hp = getPlayCampaignMemberHp(campaignId, actor.username) as PlayCampaignMemberHpRow;
  const hpCurrent = body.type === "long" ? hp.hp_max : hp.hp_current;
  if (body.type === "long" && hpCurrent !== hp.hp_current) {
    db.prepare("UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?").run(
      hpCurrent,
      campaignId,
      actor.username,
    );
  }

  const sequence = nextPlayCampaignEventSequence(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, 'rest', ?, ?)",
  ).run(campaignId, sequence, actor.username, body.type);

  db.prepare("UPDATE play_campaigns SET current_actor = ?, turn_phase = 'dm' WHERE id = ?").run(
    campaign.owner,
    campaignId,
  );
  resetPlayCampaignTurnTimeout(campaignId, campaign.turn_number ?? 1);

  sendJson(res, 201, {
    sequence,
    kind: "rest",
    actor: actor.username,
    type: body.type,
    hp_current: hpCurrent,
    hp_max: hp.hp_max,
    next_actor: "dm",
  });
}

// --- GM status overview -----------------------------------------------------

export function handleGetGmStatus(res: ServerResponse, authHeader: string | undefined, campaignId: string): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const party = playCampaignMemberSummaries(campaignId).map((member) => ({
    username: member.username,
    character_id: member.character_id,
    name: member.name,
    class: member.class,
  }));

  sendJson(res, 200, {
    campaign_id: campaignId,
    needs_attention: campaign.current_actor === campaign.owner,
    current_actor: campaign.current_actor,
    party,
    recent_events: recentPlayCampaignEvents(campaignId),
  });
}

// --- Combat encounters: lifecycle, roster, and turn-order engine -----------

function getPlayCampaignEncounter(campaignId: string, encounterId: string): { status: string } | undefined {
  return db
    .prepare("SELECT status FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?")
    .get(campaignId, encounterId) as { status: string } | undefined;
}

function hasActivePlayCampaignEncounter(campaignId: string): boolean {
  const row = db
    .prepare("SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active'")
    .get(campaignId);
  return row !== undefined;
}

interface PlayCampaignCombatStateRow {
  owner: string;
  status: string;
  current_actor: string | null;
  pre_combat_actor: string | null;
}

function getPlayCampaignCombatState(campaignId: string): PlayCampaignCombatStateRow | undefined {
  return db
    .prepare("SELECT owner, status, current_actor, pre_combat_actor FROM play_campaigns WHERE id = ?")
    .get(campaignId) as PlayCampaignCombatStateRow | undefined;
}

// The encounter is independent from the exploration turn queue: creating one
// does not touch play_campaigns.status or current_actor, since combat runs
// its own lifecycle until the campaign returns to exploration.
export function handleCreatePlayEncounter(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignCombatState(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    typeof body.name !== "string" ||
    !PLAY_CAMPAIGN_ID_RE.test(body.id) ||
    body.name.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayCampaignEncounter(campaignId, body.id) || hasActivePlayCampaignEncounter(campaignId)) {
    sendJson(res, 409, { error: "cannot create encounter" });
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_encounters (campaign_id, id, name, status, combatants) VALUES (?, ?, ?, 'active', '[]')",
  ).run(campaignId, body.id, body.name);

  // Entering combat snapshots the exploration actor so it can be restored
  // once the encounter ends; only set it the first time (a campaign already
  // mid-combat keeps its original pre-combat actor).
  if (campaign.pre_combat_actor === null) {
    db.prepare("UPDATE play_campaigns SET pre_combat_actor = ? WHERE id = ?").run(
      campaign.current_actor,
      campaignId,
    );
  }

  sendJson(res, 201, { id: body.id, name: body.name, status: "active", combatants: [] });
}

interface EncounterMonster {
  monster_id: string;
  name: string;
  hp_max: number;
  initiative: number;
  hp_current: number;
}

function getPlayCampaignEncounterCombatants(campaignId: string, encounterId: string): EncounterMonster[] | undefined {
  const row = db
    .prepare("SELECT combatants FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?")
    .get(campaignId, encounterId) as { combatants: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.combatants) as EncounterMonster[];
}

export function handleAddPlayEncounterMonster(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const combatants = getPlayCampaignEncounterCombatants(campaignId, encounterId);
  if (!combatants) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.monster_id !== "string" ||
    typeof body.name !== "string" ||
    typeof body.hp_max !== "number" ||
    typeof body.initiative !== "number" ||
    body.monster_id.length === 0 ||
    body.name.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (combatants.some((monster) => monster.monster_id === body.monster_id)) {
    sendJson(res, 409, { error: "monster already exists" });
    return;
  }

  const monster: EncounterMonster = {
    monster_id: body.monster_id,
    name: body.name,
    hp_max: body.hp_max,
    initiative: body.initiative,
    hp_current: body.hp_max,
  };
  combatants.push(monster);

  db.prepare("UPDATE play_campaign_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?").run(
    JSON.stringify(combatants),
    campaignId,
    encounterId,
  );

  sendJson(res, 201, monster);
}

export function handleRemovePlayEncounterMonster(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  monsterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const combatants = getPlayCampaignEncounterCombatants(campaignId, encounterId);
  if (!combatants) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  const nextCombatants = combatants.filter((monster) => monster.monster_id !== monsterId);
  if (nextCombatants.length === combatants.length) {
    sendJson(res, 404, { error: "monster not found" });
    return;
  }

  db.prepare("UPDATE play_campaign_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?").run(
    JSON.stringify(nextCombatants),
    campaignId,
    encounterId,
  );

  sendJson(res, 200, { removed: monsterId });
}

interface PartyCombatant {
  member: string;
  character_id: string;
  name: string;
  initiative: number;
}

function getPlayCampaignEncounterPartyCombatants(
  campaignId: string,
  encounterId: string,
): PartyCombatant[] | undefined {
  const row = db
    .prepare("SELECT party_combatants FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?")
    .get(campaignId, encounterId) as { party_combatants: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.party_combatants) as PartyCombatant[];
}

export function handleBindPlayEncounterCombatant(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const combatants = getPlayCampaignEncounterPartyCombatants(campaignId, encounterId);
  if (!combatants) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.member !== "string" ||
    typeof body.initiative !== "number" ||
    body.member.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const member = getPlayCampaignMemberCharacter(campaignId, body.member);
  if (!member) {
    sendJson(res, 400, { error: "member not found" });
    return;
  }

  if (combatants.some((combatant) => combatant.member === body.member)) {
    sendJson(res, 409, { error: "member already bound" });
    return;
  }

  const combatant: PartyCombatant = {
    member: body.member,
    character_id: member.character_id,
    name: member.name,
    initiative: body.initiative,
  };
  combatants.push(combatant);

  db.prepare("UPDATE play_campaign_encounters SET party_combatants = ? WHERE campaign_id = ? AND id = ?").run(
    JSON.stringify(combatants),
    campaignId,
    encounterId,
  );

  sendJson(res, 201, combatant);
}

interface EncounterTurnRow {
  combatants: string;
  party_combatants: string;
  turn_round: number;
  turn_index: number;
  conditions: string;
  turn_order: string | null;
  ready_actions: string;
}

function getPlayCampaignEncounterTurnState(campaignId: string, encounterId: string): EncounterTurnRow | undefined {
  return db
    .prepare(
      "SELECT combatants, party_combatants, turn_round, turn_index, conditions, turn_order, ready_actions FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?",
    )
    .get(campaignId, encounterId) as EncounterTurnRow | undefined;
}

interface EncounterCondition {
  condition: string;
  remaining_rounds: number;
}

type EncounterConditionMap = Record<string, EncounterCondition[]>;

function parseEncounterConditions(row: EncounterTurnRow): EncounterConditionMap {
  return JSON.parse(row.conditions) as EncounterConditionMap;
}

function saveEncounterConditions(
  campaignId: string,
  encounterId: string,
  conditions: EncounterConditionMap,
): void {
  db.prepare("UPDATE play_campaign_encounters SET conditions = ? WHERE campaign_id = ? AND id = ?").run(
    JSON.stringify(conditions),
    campaignId,
    encounterId,
  );
}

interface EncounterOrderEntry {
  name: string;
  kind: "monster" | "player";
  initiative: number;
  member?: string;
  target: string;
}

// Deterministic initiative order: monsters first, then bound party members
// (each group in its stored/insertion order), stable-sorted by initiative
// descending so ties keep that same relative order every time.
function defaultEncounterOrder(row: EncounterTurnRow): EncounterOrderEntry[] {
  const monsters = JSON.parse(row.combatants) as EncounterMonster[];
  const party = JSON.parse(row.party_combatants) as PartyCombatant[];
  const combined: EncounterOrderEntry[] = [
    ...monsters.map((monster) => ({
      name: monster.name,
      kind: "monster" as const,
      initiative: monster.initiative,
      target: monster.monster_id,
    })),
    ...party.map((combatant) => ({
      name: combatant.name,
      kind: "player" as const,
      initiative: combatant.initiative,
      member: combatant.member,
      target: combatant.member,
    })),
  ];
  return combined
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => b.entry.initiative - a.entry.initiative || a.index - b.index)
    .map(({ entry }) => entry);
}

// A delay call persists an explicit turn_order override (a list of target
// ids) so the current combatant can be reinserted at a later position
// without re-deriving the order from initiative each time.
function buildEncounterOrder(row: EncounterTurnRow): EncounterOrderEntry[] {
  const defaultOrder = defaultEncounterOrder(row);
  if (!row.turn_order) return defaultOrder;

  const byTarget = new Map(defaultOrder.map((entry) => [entry.target, entry]));
  const overrideTargets = JSON.parse(row.turn_order) as string[];
  const ordered = overrideTargets.map((target) => byTarget.get(target)).filter((entry): entry is EncounterOrderEntry => entry !== undefined);
  if (ordered.length !== defaultOrder.length) return defaultOrder;
  return ordered;
}

function activeEncounterCombatant(row: EncounterTurnRow): EncounterOrderEntry | undefined {
  const order = buildEncounterOrder(row);
  if (order.length === 0) return undefined;
  return order[row.turn_index % order.length];
}

export function handleGetEncounterTurn(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const turnState = getPlayCampaignEncounterTurnState(campaignId, encounterId);
  if (!turnState) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  const active = activeEncounterCombatant(turnState);

  sendJson(res, 200, {
    round: turnState.turn_round,
    turn_index: turnState.turn_index,
    active: active ? { name: active.name, kind: active.kind, initiative: active.initiative } : null,
  });
}

export function handleAdvanceEncounterTurn(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const turnState = getPlayCampaignEncounterTurnState(campaignId, encounterId);
  if (!turnState) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  const order = buildEncounterOrder(turnState);
  if (order.length === 0) {
    sendJson(res, 409, { error: "no combatants" });
    return;
  }

  const active = order[turnState.turn_index % order.length];
  const isCurrentCombatant = active.kind === "player" && active.member === actor.username;
  if (!isOwner && !isCurrentCombatant) {
    sendJson(res, 409, { error: "not your turn" });
    return;
  }

  let nextIndex = turnState.turn_index + 1;
  let nextRound = turnState.turn_round;
  if (nextIndex >= order.length) {
    nextIndex = 0;
    nextRound += 1;
  }

  const nextActive = order[nextIndex];

  const conditions = parseEncounterConditions(turnState);
  const activeConditions = conditions[nextActive.target];
  if (activeConditions && activeConditions.length > 0) {
    conditions[nextActive.target] = activeConditions
      .map((entry) => ({ ...entry, remaining_rounds: entry.remaining_rounds - 1 }))
      .filter((entry) => entry.remaining_rounds > 0);
    if (conditions[nextActive.target].length === 0) {
      delete conditions[nextActive.target];
    }
  }

  db.prepare(
    "UPDATE play_campaign_encounters SET turn_round = ?, turn_index = ?, conditions = ? WHERE campaign_id = ? AND id = ?",
  ).run(nextRound, nextIndex, JSON.stringify(conditions), campaignId, encounterId);

  sendJson(res, 200, {
    round: nextRound,
    turn_index: nextIndex,
    active: { name: nextActive.name, kind: nextActive.kind, initiative: nextActive.initiative },
  });
}

export function handleDelayEncounterTurn(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const turnState = getPlayCampaignEncounterTurnState(campaignId, encounterId);
  if (!turnState) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  const order = buildEncounterOrder(turnState);
  if (order.length === 0) {
    sendJson(res, 409, { error: "no combatants" });
    return;
  }

  const currentPosition = turnState.turn_index % order.length;
  const active = order[currentPosition];
  const isCurrentCombatant = active.kind === "player" && active.member === actor.username;
  if (!isOwner && !isCurrentCombatant) {
    sendJson(res, 409, { error: "not your turn" });
    return;
  }

  if (!isPlainObject(body) || !isValidInt(body.new_index, 0, order.length - 1)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const newIndex = body.new_index;
  if (newIndex <= currentPosition) {
    sendJson(res, 400, { error: "delay must move to a later position" });
    return;
  }

  const withoutActive = order.filter((_, index) => index !== currentPosition);
  withoutActive.splice(newIndex, 0, active);

  db.prepare("UPDATE play_campaign_encounters SET turn_order = ?, turn_index = ? WHERE campaign_id = ? AND id = ?").run(
    JSON.stringify(withoutActive.map((entry) => entry.target)),
    newIndex,
    campaignId,
    encounterId,
  );

  sendJson(res, 200, {
    round: turnState.turn_round,
    turn_index: newIndex,
    order: withoutActive.map((entry) => ({ name: entry.name, kind: entry.kind, initiative: entry.initiative })),
  });
}

export function handleReadyEncounterTurn(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const turnState = getPlayCampaignEncounterTurnState(campaignId, encounterId);
  if (!turnState) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  const active = activeEncounterCombatant(turnState);
  const isCurrentCombatant = active !== undefined && active.kind === "player" && active.member === actor.username;
  if (!isCurrentCombatant) {
    sendJson(res, 409, { error: "not your turn" });
    return;
  }

  if (!isPlainObject(body) || typeof body.trigger !== "string" || body.trigger.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const readyActions = JSON.parse(turnState.ready_actions) as { actor: string; trigger: string }[];
  const record = { actor: actor.username, trigger: body.trigger };
  readyActions.push(record);

  db.prepare("UPDATE play_campaign_encounters SET ready_actions = ? WHERE campaign_id = ? AND id = ?").run(
    JSON.stringify(readyActions),
    campaignId,
    encounterId,
  );

  sendJson(res, 201, record);
}

const COMBAT_ACTION_TYPES = new Set(["attack", "help", "dodge", "ready"]);

export function handleSubmitEncounterCombatAction(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const turnState = getPlayCampaignEncounterTurnState(campaignId, encounterId);
  if (!turnState) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  const active = activeEncounterCombatant(turnState);
  const isCurrentCombatant = active !== undefined && active.kind === "player" && active.member === actor.username;
  if (!isCurrentCombatant) {
    sendJson(res, 409, { error: "not your turn" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.type !== "string" ||
    !COMBAT_ACTION_TYPES.has(body.type) ||
    typeof body.text !== "string" ||
    body.text.length === 0 ||
    (body.target !== undefined && typeof body.target !== "string")
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const target = body.target ?? null;
  const sequence = nextPlayCampaignEventSequence(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, action_type, action_target) VALUES (?, ?, 'combat_action', ?, ?, ?, ?)",
  ).run(campaignId, sequence, actor.username, body.text, body.type, target);

  sendJson(res, 201, {
    sequence,
    kind: "combat_action",
    actor: actor.username,
    type: body.type,
    target,
    text: body.text,
  });
}

export function handleUnbindPlayEncounterCombatant(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  member: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const combatants = getPlayCampaignEncounterPartyCombatants(campaignId, encounterId);
  if (!combatants) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  const nextCombatants = combatants.filter((combatant) => combatant.member !== member);
  if (nextCombatants.length === combatants.length) {
    sendJson(res, 404, { error: "member not found" });
    return;
  }

  db.prepare("UPDATE play_campaign_encounters SET party_combatants = ? WHERE campaign_id = ? AND id = ?").run(
    JSON.stringify(nextCombatants),
    campaignId,
    encounterId,
  );

  sendJson(res, 200, { removed: member });
}

interface ResolvedEncounterTarget {
  hp_current: number;
  hp_max: number;
  apply: (hpAfter: number) => void;
}

// A damage/heal target is either a bound monster combatant (hp stored in the
// encounter's own `combatants` JSON) or a bound party member (hp stored on
// play_campaign_members, shared with the rest-turn HP tracking).
function resolveEncounterTarget(
  campaignId: string,
  encounterId: string,
  target: string,
): ResolvedEncounterTarget | undefined {
  const monsters = getPlayCampaignEncounterCombatants(campaignId, encounterId);
  if (!monsters) return undefined;

  const monster = monsters.find((m) => m.monster_id === target);
  if (monster) {
    return {
      hp_current: monster.hp_current,
      hp_max: monster.hp_max,
      apply: (hpAfter) => {
        monster.hp_current = hpAfter;
        db.prepare("UPDATE play_campaign_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?").run(
          JSON.stringify(monsters),
          campaignId,
          encounterId,
        );
      },
    };
  }

  const party = getPlayCampaignEncounterPartyCombatants(campaignId, encounterId);
  if (!party) return undefined;

  const combatant = party.find((p) => p.member === target);
  if (!combatant) return undefined;

  const hp = getPlayCampaignMemberHp(campaignId, combatant.member);
  if (!hp) return undefined;

  return {
    hp_current: hp.hp_current,
    hp_max: hp.hp_max,
    apply: (hpAfter) => {
      db.prepare("UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?").run(
        hpAfter,
        campaignId,
        combatant.member,
      );
    },
  };
}

export function handleAddPlayEncounterCondition(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const turnState = getPlayCampaignEncounterTurnState(campaignId, encounterId);
  if (!turnState) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.target !== "string" ||
    body.target.length === 0 ||
    typeof body.condition !== "string" ||
    body.condition.length === 0 ||
    !isValidInt(body.duration_rounds, 1, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!resolveEncounterTarget(campaignId, encounterId, body.target)) {
    sendJson(res, 404, { error: "target not found" });
    return;
  }

  const conditions = parseEncounterConditions(turnState);
  const targetConditions = conditions[body.target] ?? [];
  const existing = targetConditions.find((entry) => entry.condition === body.condition);
  if (existing) {
    existing.remaining_rounds = body.duration_rounds;
  } else {
    targetConditions.push({ condition: body.condition, remaining_rounds: body.duration_rounds });
  }
  conditions[body.target] = targetConditions;
  saveEncounterConditions(campaignId, encounterId, conditions);

  sendJson(res, 201, {
    target: body.target,
    conditions: targetConditions,
  });
}

export function handleGetPlayEncounterStatus(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const turnState = getPlayCampaignEncounterTurnState(campaignId, encounterId);
  if (!turnState) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  const order = buildEncounterOrder(turnState);
  const active = order.length > 0 ? order[turnState.turn_index % order.length] : undefined;
  const conditions = parseEncounterConditions(turnState);

  sendJson(res, 200, {
    round: turnState.turn_round,
    turn_index: turnState.turn_index,
    active: active ? { name: active.name, kind: active.kind, initiative: active.initiative } : null,
    order: order.map((entry) => ({ name: entry.name, kind: entry.kind, initiative: entry.initiative })),
    conditions,
  });
}

export function handleDamagePlayEncounterCombatant(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!getPlayCampaignEncounter(campaignId, encounterId)) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.target !== "string" ||
    body.target.length === 0 ||
    !isValidInt(body.amount, 0, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const resolved = resolveEncounterTarget(campaignId, encounterId, body.target);
  if (!resolved) {
    sendJson(res, 404, { error: "target not found" });
    return;
  }

  const hpAfter = Math.max(0, resolved.hp_current - body.amount);
  resolved.apply(hpAfter);

  sendJson(res, 200, {
    target: body.target,
    hp_before: resolved.hp_current,
    hp_after: hpAfter,
    damage: body.amount,
  });
}

export function handleHealPlayEncounterCombatant(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!getPlayCampaignEncounter(campaignId, encounterId)) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.target !== "string" ||
    body.target.length === 0 ||
    !isValidInt(body.amount, 0, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const resolved = resolveEncounterTarget(campaignId, encounterId, body.target);
  if (!resolved) {
    sendJson(res, 404, { error: "target not found" });
    return;
  }

  const hpAfter = Math.min(resolved.hp_max, resolved.hp_current + body.amount);
  resolved.apply(hpAfter);

  sendJson(res, 200, {
    target: body.target,
    hp_before: resolved.hp_current,
    hp_after: hpAfter,
    healing: body.amount,
  });
}

interface PlayCampaignMemberByCharacterRow {
  username: string;
  hp_current: number;
  hp_max: number;
  status: string;
  death_save_successes: number;
  death_save_failures: number;
}

// --- Character HP / status / death saves ------------------------------------

function getPlayCampaignMemberByCharacterId(
  campaignId: string,
  characterId: string,
): PlayCampaignMemberByCharacterRow | undefined {
  return db
    .prepare(
      "SELECT username, hp_current, hp_max, status, death_save_successes, death_save_failures " +
        "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
    )
    .get(campaignId, characterId) as PlayCampaignMemberByCharacterRow | undefined;
}

export function handleDamagePlayCharacter(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const member = getPlayCampaignMemberByCharacterId(campaignId, characterId);
  if (!member) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (!isPlainObject(body) || !isValidInt(body.amount, 0, Number.MAX_SAFE_INTEGER)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const hpAfter = Math.max(0, member.hp_current - body.amount);
  const status = hpAfter === 0 && member.status === "conscious" ? "unconscious" : member.status;
  const resetDeathSaves = status === "unconscious" && member.status === "conscious";

  db.prepare(
    "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = ?, death_save_failures = ? " +
      "WHERE campaign_id = ? AND character_id = ?",
  ).run(
    hpAfter,
    status,
    resetDeathSaves ? 0 : member.death_save_successes,
    resetDeathSaves ? 0 : member.death_save_failures,
    campaignId,
    characterId,
  );

  sendJson(res, 200, {
    character_id: characterId,
    target: characterId,
    hp_before: member.hp_current,
    hp_after: hpAfter,
    damage: body.amount,
    status,
  });
}

const DEATH_SAVE_OUTCOMES = new Set(["success", "failure"]);

export function handleRecordDeathSave(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  if (!hasPlayCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const member = getPlayCampaignMemberByCharacterId(campaignId, characterId);
  if (!member) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (actor.username !== member.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.outcome !== "string" ||
    !DEATH_SAVE_OUTCOMES.has(body.outcome)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (member.status !== "unconscious") {
    sendJson(res, 409, { error: "character is not making death saves" });
    return;
  }

  let successes = member.death_save_successes;
  let failures = member.death_save_failures;
  if (body.outcome === "success") {
    successes += 1;
  } else {
    failures += 1;
  }

  let status = member.status;
  if (successes >= 3) {
    status = "stable";
  } else if (failures >= 3) {
    status = "dead";
  }

  db.prepare(
    "UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ?, status = ? " +
      "WHERE campaign_id = ? AND character_id = ?",
  ).run(successes, failures, status, campaignId, characterId);

  sendJson(res, 201, {
    character_id: characterId,
    successes,
    failures,
    status,
  });
}

export function handleGetCharacterStatus(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isMember = hasPlayCampaignMember(campaignId, actor.username);
  if (!isMember && actor.username !== campaign.owner) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const member = getPlayCampaignMemberByCharacterId(campaignId, characterId);
  if (!member) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  sendJson(res, 200, {
    character_id: characterId,
    hp_current: member.hp_current,
    hp_max: member.hp_max,
    status: member.status,
  });
}

interface LootAward {
  slug: string;
  quantity: number;
}

// --- Encounter rewards and closing out combat -------------------------------

function getPlayCampaignEncounterRewardState(
  campaignId: string,
  encounterId: string,
): { rewarded: number } | undefined {
  return db
    .prepare("SELECT rewarded FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?")
    .get(campaignId, encounterId) as { rewarded: number } | undefined;
}

export function handleAwardEncounterRewards(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const encounter = getPlayCampaignEncounterRewardState(campaignId, encounterId);
  if (!encounter) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    !isValidInt(body.xp, 0, Number.MAX_SAFE_INTEGER) ||
    !Array.isArray(body.loot) ||
    !body.loot.every(
      (entry): entry is LootAward =>
        isPlainObject(entry) &&
        typeof entry.slug === "string" &&
        entry.slug.length > 0 &&
        isValidInt(entry.quantity, 1, Number.MAX_SAFE_INTEGER),
    )
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (encounter.rewarded) {
    sendJson(res, 409, { error: "rewards already awarded" });
    return;
  }

  const loot = body.loot as LootAward[];

  db.prepare(
    "UPDATE play_campaign_encounters SET xp_awarded = ?, loot = ?, rewarded = 1 WHERE campaign_id = ? AND id = ?",
  ).run(body.xp, JSON.stringify(loot), campaignId, encounterId);

  sendJson(res, 200, { id: encounterId, xp: body.xp, loot });
}

function getPlayCampaignEncounterCloseState(
  campaignId: string,
  encounterId: string,
): { xp_awarded: number } | undefined {
  return db
    .prepare("SELECT xp_awarded FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?")
    .get(campaignId, encounterId) as { xp_awarded: number } | undefined;
}

export function handleClosePlayEncounter(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const encounter = getPlayCampaignEncounterCloseState(campaignId, encounterId);
  if (!encounter) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  db.prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ?").run(
    campaignId,
    encounterId,
  );

  sendJson(res, 200, { id: encounterId, status: "closed", xp_awarded: encounter.xp_awarded });
}

export function handleEndPlayEncounter(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignCombatState(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const encounter = getPlayCampaignEncounter(campaignId, encounterId);
  if (!encounter) {
    sendJson(res, 404, { error: "encounter not found" });
    return;
  }

  if (campaign.pre_combat_actor === null) {
    sendJson(res, 409, { error: "campaign is not in combat" });
    return;
  }

  if (encounter.status === "active") {
    db.prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ?").run(
      campaignId,
      encounterId,
    );
  }

  db.prepare(
    "UPDATE play_campaigns SET current_actor = ?, pre_combat_actor = NULL, turn_phase = 'exploration' WHERE id = ?",
  ).run(campaign.owner, campaignId);

  sendJson(res, 200, {
    campaign_id: campaignId,
    status: campaign.status,
    phase: "exploration",
    current_actor: campaign.owner,
  });
}

interface PlayCampaignCharacterOwnerRow {
  character_id: string;
  owner: string | null;
}

// --- Character ownership (claim / transfer) ---------------------------------

function getPlayCampaignCharacterOwner(
  campaignId: string,
  characterId: string,
): PlayCampaignCharacterOwnerRow | undefined {
  return db
    .prepare("SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?")
    .get(campaignId, characterId) as PlayCampaignCharacterOwnerRow | undefined;
}

export function handleGetCharacterOwner(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  sendJson(res, 200, { character_id: character.character_id, owner: character.owner });
}

export function handleClaimCharacter(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (actor.role !== "player" || !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner !== null && character.owner !== actor.username) {
    sendJson(res, 409, { error: "character already owned" });
    return;
  }

  db.prepare("UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?").run(
    actor.username,
    campaignId,
    characterId,
  );

  sendJson(res, 201, { character_id: characterId, owner: actor.username });
}

export function handleTransferCharacter(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!isPlainObject(body) || typeof body.new_owner !== "string" || body.new_owner.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!hasPlayCampaignMember(campaignId, body.new_owner)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  db.prepare("UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?").run(
    body.new_owner,
    campaignId,
    characterId,
  );

  sendJson(res, 200, { character_id: characterId, owner: body.new_owner });
}

// --- Character build (race/class/background/abilities) and progression -----

const VALID_RACES = new Set([
  "human",
  "elf",
  "dwarf",
  "halfling",
  "gnome",
  "half-elf",
  "half-orc",
  "dragonborn",
  "tiefling",
]);

const VALID_BACKGROUNDS = new Set([
  "acolyte",
  "charlatan",
  "criminal",
  "entertainer",
  "folk hero",
  "guild artisan",
  "hermit",
  "noble",
  "outlander",
  "sage",
  "sailor",
  "soldier",
  "urchin",
]);

// Level-1 hit die by class (5e PHB); hp_max at level 1 is hit die + CON modifier.
const CLASS_HIT_DIE: Record<string, number> = {
  barbarian: 12,
  fighter: 10,
  paladin: 10,
  ranger: 10,
  bard: 8,
  cleric: 8,
  druid: 8,
  monk: 8,
  rogue: 8,
  warlock: 8,
  sorcerer: 6,
  wizard: 6,
};

interface CharacterBuildAbilities {
  str: number;
  dex: number;
  con: number;
  int: number;
  wis: number;
  cha: number;
}

const ABILITY_KEYS: (keyof CharacterBuildAbilities)[] = ["str", "dex", "con", "int", "wis", "cha"];

export function handleBuildCharacter(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.race !== "string" ||
    typeof body.class !== "string" ||
    typeof body.background !== "string" ||
    !isPlainObject(body.abilities)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!VALID_RACES.has(body.race) || !CLASS_HIT_DIE[body.class] || !VALID_BACKGROUNDS.has(body.background)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const abilitiesInput = body.abilities;
  for (const key of ABILITY_KEYS) {
    if (!isValidInt(abilitiesInput[key], 1, 30)) {
      sendJson(res, 400, { error: "invalid request" });
      return;
    }
  }

  const abilities = abilitiesInput as unknown as CharacterBuildAbilities;
  const conModifier = abilityModifier(abilities.con);
  const strModifier = abilityModifier(abilities.str);
  const dexModifier = abilityModifier(abilities.dex);
  const intModifier = abilityModifier(abilities.int);
  const wisModifier = abilityModifier(abilities.wis);
  const chaModifier = abilityModifier(abilities.cha);
  const level = 1;
  const hpMax = CLASS_HIT_DIE[body.class] + conModifier;
  const bonus = 2;

  db.prepare(
    "UPDATE play_campaign_members SET class = ?, race = ?, background = ?, level = ?, hp_current = ?, hp_max = ?, " +
      "proficiency_bonus = ?, con_modifier = ?, str_modifier = ?, dex_modifier = ?, int_modifier = ?, wis_modifier = ?, cha_modifier = ? " +
      "WHERE campaign_id = ? AND character_id = ?",
  ).run(
    body.class,
    body.race,
    body.background,
    level,
    hpMax,
    hpMax,
    bonus,
    conModifier,
    strModifier,
    dexModifier,
    intModifier,
    wisModifier,
    chaModifier,
    campaignId,
    characterId,
  );

  sendJson(res, 200, {
    character_id: characterId,
    race: body.race,
    class: body.class,
    background: body.background,
    level,
    hp_max: hpMax,
    proficiency_bonus: bonus,
  });
}

interface PlayCampaignCharacterLevelRow {
  owner: string | null;
  class: string;
  level: number;
  hp_max: number;
  con_modifier: number;
}

function getPlayCampaignCharacterLevelRow(
  campaignId: string,
  characterId: string,
): PlayCampaignCharacterLevelRow | undefined {
  return db
    .prepare(
      "SELECT owner, class, level, hp_max, con_modifier FROM play_campaign_members " +
        "WHERE campaign_id = ? AND character_id = ?",
    )
    .get(campaignId, characterId) as PlayCampaignCharacterLevelRow | undefined;
}

export function handleLevelUpCharacter(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterLevelRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!isPlainObject(body) || !isValidInt(body.level, 1, 20)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const newLevel = body.level as number;
  if (newLevel !== character.level + 1) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const hitDie = CLASS_HIT_DIE[character.class];
  if (!hitDie) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const hpGain = Math.floor(hitDie / 2) + 1 + character.con_modifier;
  const newHpMax = character.hp_max + hpGain;
  const newProficiencyBonus = proficiencyBonus(newLevel);

  db.prepare(
    "UPDATE play_campaign_members SET level = ?, hp_max = ?, hp_current = hp_current + ?, proficiency_bonus = ? " +
      "WHERE campaign_id = ? AND character_id = ?",
  ).run(newLevel, newHpMax, hpGain, newProficiencyBonus, campaignId, characterId);

  sendJson(res, 200, {
    character_id: characterId,
    level: newLevel,
    hp_max: newHpMax,
    hit_dice: `1d${hitDie}`,
    proficiency_bonus: newProficiencyBonus,
  });
}

const VALID_ABILITIES = new Set(["str", "dex", "con", "int", "wis", "cha"]);

const VALID_SKILLS = new Set([
  "acrobatics",
  "animal-handling",
  "arcana",
  "athletics",
  "deception",
  "history",
  "insight",
  "intimidation",
  "investigation",
  "medicine",
  "nature",
  "perception",
  "performance",
  "persuasion",
  "religion",
  "sleight-of-hand",
  "stealth",
  "survival",
]);

interface PlayCampaignCharacterSkillRow {
  owner: string | null;
  proficiency_bonus: number;
  str_modifier: number;
  dex_modifier: number;
  con_modifier: number;
  int_modifier: number;
  wis_modifier: number;
  cha_modifier: number;
}

function getPlayCampaignCharacterSkillRow(
  campaignId: string,
  characterId: string,
): PlayCampaignCharacterSkillRow | undefined {
  return db
    .prepare(
      "SELECT owner, proficiency_bonus, str_modifier, dex_modifier, con_modifier, int_modifier, wis_modifier, cha_modifier " +
        "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
    )
    .get(campaignId, characterId) as PlayCampaignCharacterSkillRow | undefined;
}

export function handleSkillCheck(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterSkillRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.skill !== "string" ||
    typeof body.ability !== "string" ||
    typeof body.proficient !== "boolean" ||
    typeof body.roll !== "number" ||
    !Number.isInteger(body.roll) ||
    !VALID_SKILLS.has(body.skill) ||
    !VALID_ABILITIES.has(body.ability)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const abilityModifierByKey: Record<string, number> = {
    str: character.str_modifier,
    dex: character.dex_modifier,
    con: character.con_modifier,
    int: character.int_modifier,
    wis: character.wis_modifier,
    cha: character.cha_modifier,
  };

  const modifier = abilityModifierByKey[body.ability] + (body.proficient ? character.proficiency_bonus : 0);
  const total = body.roll + modifier;

  sendJson(res, 200, {
    character_id: characterId,
    skill: body.skill,
    ability: body.ability,
    modifier,
    total,
  });
}

// --- Spellbook: known spells, validated against class -----------------------

// Only these classes can learn spells at all (5e PHB); others (barbarian,
// fighter, monk, rogue, ...) never have a valid spell/class combination.
const SPELLCASTING_CLASSES = new Set([
  "bard",
  "cleric",
  "druid",
  "paladin",
  "ranger",
  "sorcerer",
  "warlock",
  "wizard",
]);

interface PlayCampaignCharacterClassRow {
  owner: string | null;
  class: string;
}

function getPlayCampaignCharacterClassRow(
  campaignId: string,
  characterId: string,
): PlayCampaignCharacterClassRow | undefined {
  return db
    .prepare("SELECT owner, class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?")
    .get(campaignId, characterId) as PlayCampaignCharacterClassRow | undefined;
}

function hasPlayCampaignSpell(campaignId: string, characterId: string, spellId: string): boolean {
  const row = db
    .prepare(
      "SELECT 1 FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
    )
    .get(campaignId, characterId, spellId);
  return row !== undefined;
}

export function handleAddPlaySpell(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterClassRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.spell_id !== "string" ||
    body.spell_id.length === 0 ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    !isValidInt(body.level, 0, 9)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!SPELLCASTING_CLASSES.has(character.class)) {
    sendJson(res, 400, { error: "invalid class/spell combination" });
    return;
  }

  if (hasPlayCampaignSpell(campaignId, characterId, body.spell_id)) {
    sendJson(res, 409, { error: "spell already known" });
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, characterId, body.spell_id, body.name, body.level);

  sendJson(res, 201, { spell_id: body.spell_id, name: body.name, level: body.level });
}

export function handleGetPlaySpells(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (!getPlayCampaignCharacterClassRow(campaignId, characterId)) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  const spells = db
    .prepare(
      "SELECT spell_id, name, level FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC",
    )
    .all(campaignId, characterId) as { spell_id: string; name: string; level: number }[];

  sendJson(res, 200, { spells });
}

// --- Prepared spells: a subset of known spells, capped by class/level -------

// Primary spellcasting ability per class, used to compute how many spells a
// character may prepare at once (5e PHB: ability modifier + caster level,
// minimum 1).
const SPELLCASTING_ABILITY_COLUMN: Record<string, "int_modifier" | "wis_modifier" | "cha_modifier"> = {
  wizard: "int_modifier",
  cleric: "wis_modifier",
  druid: "wis_modifier",
  ranger: "wis_modifier",
  paladin: "cha_modifier",
  bard: "cha_modifier",
  sorcerer: "cha_modifier",
  warlock: "cha_modifier",
};

interface PlayCampaignCharacterCasterRow {
  owner: string | null;
  class: string;
  level: number;
  int_modifier: number;
  wis_modifier: number;
  cha_modifier: number;
}

function getPlayCampaignCharacterCasterRow(
  campaignId: string,
  characterId: string,
): PlayCampaignCharacterCasterRow | undefined {
  return db
    .prepare(
      "SELECT owner, class, level, int_modifier, wis_modifier, cha_modifier FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
    )
    .get(campaignId, characterId) as PlayCampaignCharacterCasterRow | undefined;
}

function maxPreparedSpells(character: PlayCampaignCharacterCasterRow): number {
  const abilityColumn = SPELLCASTING_ABILITY_COLUMN[character.class];
  if (!abilityColumn) return 0;
  return Math.max(1, character.level + character[abilityColumn]);
}

function getPlayCampaignPreparedSpells(campaignId: string, characterId: string): string[] {
  const row = db
    .prepare("SELECT spell_ids FROM play_campaign_prepared_spells WHERE campaign_id = ? AND character_id = ?")
    .get(campaignId, characterId) as { spell_ids: string } | undefined;
  return row ? (JSON.parse(row.spell_ids) as string[]) : [];
}

export function handlePutPreparedSpells(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterCasterRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    !Array.isArray(body.spell_ids) ||
    !body.spell_ids.every((spellId): spellId is string => typeof spellId === "string" && spellId.length > 0)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!SPELLCASTING_ABILITY_COLUMN[character.class]) {
    sendJson(res, 400, { error: "invalid class/spell combination" });
    return;
  }

  const spellIds = body.spell_ids as string[];

  for (const spellId of spellIds) {
    if (!hasPlayCampaignSpell(campaignId, characterId, spellId)) {
      sendJson(res, 400, { error: "unknown spell" });
      return;
    }
  }

  const maxPrepared = maxPreparedSpells(character);
  if (spellIds.length > maxPrepared) {
    sendJson(res, 400, { error: "too many prepared spells" });
    return;
  }

  db.prepare(
    `INSERT INTO play_campaign_prepared_spells (campaign_id, character_id, spell_ids) VALUES (?, ?, ?)
     ON CONFLICT (campaign_id, character_id) DO UPDATE SET spell_ids = excluded.spell_ids`,
  ).run(campaignId, characterId, JSON.stringify(spellIds));

  sendJson(res, 200, { character_id: characterId, prepared_spells: spellIds, max_prepared: maxPrepared });
}

export function handleGetPreparedSpells(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const character = getPlayCampaignCharacterCasterRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  const preparedSpells = getPlayCampaignPreparedSpells(campaignId, characterId);
  const maxPrepared = maxPreparedSpells(character);

  sendJson(res, 200, { character_id: characterId, prepared_spells: preparedSpells, max_prepared: maxPrepared });
}

// --- Spell casting: consume a prepared spell's slot -------------------------

function getPlayCampaignSpellLevel(
  campaignId: string,
  characterId: string,
  spellId: string,
): number | undefined {
  const row = db
    .prepare(
      "SELECT level FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
    )
    .get(campaignId, characterId, spellId) as { level: number } | undefined;
  return row?.level;
}

// Slots available at a given spell level scale linearly with character
// level: one slot at the level a caster first gains access to that spell
// level, plus one more per level thereafter (level 1 wizard -> one 1st-level
// slot, matching the PHB baseline for a fresh spellcaster).
function spellSlotsForLevel(characterLevel: number, spellLevel: number): number {
  return Math.max(0, characterLevel - spellLevel + 1);
}

function countPlayCampaignCastsAtLevel(campaignId: string, characterId: string, slotLevel: number): number {
  const row = db
    .prepare(
      "SELECT COUNT(*) AS count FROM play_campaign_casts WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
    )
    .get(campaignId, characterId, slotLevel) as { count: number };
  return row.count;
}

function nextPlayCampaignCastSequence(campaignId: string, characterId: string): number {
  const row = db
    .prepare(
      "SELECT MAX(sequence) AS max_sequence FROM play_campaign_casts WHERE campaign_id = ? AND character_id = ?",
    )
    .get(campaignId, characterId) as { max_sequence: number | null };
  return (row.max_sequence ?? 0) + 1;
}

export function handleCastPlaySpell(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterCasterRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.spell_id !== "string" ||
    body.spell_id.length === 0 ||
    typeof body.target !== "string" ||
    body.target.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!SPELLCASTING_ABILITY_COLUMN[character.class]) {
    sendJson(res, 400, { error: "not a spellcaster" });
    return;
  }

  const preparedSpells = getPlayCampaignPreparedSpells(campaignId, characterId);
  if (!preparedSpells.includes(body.spell_id)) {
    sendJson(res, 400, { error: "spell not prepared" });
    return;
  }

  const spellLevel = getPlayCampaignSpellLevel(campaignId, characterId, body.spell_id) as number;
  const totalSlots = spellSlotsForLevel(character.level, spellLevel);
  const usedSlots = countPlayCampaignCastsAtLevel(campaignId, characterId, spellLevel);
  if (usedSlots >= totalSlots) {
    sendJson(res, 409, { error: "no spell slots remaining" });
    return;
  }

  const sequence = nextPlayCampaignCastSequence(campaignId, characterId);
  db.prepare(
    "INSERT INTO play_campaign_casts (campaign_id, character_id, sequence, spell_id, target, slot_level) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, characterId, sequence, body.spell_id, body.target, spellLevel);

  sendJson(res, 201, {
    character_id: characterId,
    spell_id: body.spell_id,
    target: body.target,
    slot_level: spellLevel,
    slots_remaining: totalSlots - usedSlots - 1,
    sequence,
  });
}

export function handleGetPlayCasts(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const character = getPlayCampaignCharacterCasterRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  const casts = db
    .prepare(
      "SELECT sequence, spell_id, target, slot_level FROM play_campaign_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId, characterId) as { sequence: number; spell_id: string; target: string; slot_level: number }[];

  const castCountAtLevel: Record<number, number> = {};
  sendJson(res, 200, {
    casts: casts.map((cast) => {
      castCountAtLevel[cast.slot_level] = (castCountAtLevel[cast.slot_level] ?? 0) + 1;
      const totalSlots = spellSlotsForLevel(character.level, cast.slot_level);
      return {
        character_id: characterId,
        spell_id: cast.spell_id,
        target: cast.target,
        slot_level: cast.slot_level,
        slots_remaining: totalSlots - castCountAtLevel[cast.slot_level],
        sequence: cast.sequence,
      };
    }),
  });
}

// --- Concentration: a single active spell a character is concentrating on --

interface PlayCampaignConcentrationRow {
  spell_id: string;
  target: string;
  remaining_turns: number;
}

function getPlayCampaignConcentration(
  campaignId: string,
  characterId: string,
): PlayCampaignConcentrationRow | undefined {
  return db
    .prepare(
      "SELECT spell_id, target, remaining_turns FROM play_campaign_concentration WHERE campaign_id = ? AND character_id = ?",
    )
    .get(campaignId, characterId) as PlayCampaignConcentrationRow | undefined;
}

function clearPlayCampaignConcentration(campaignId: string, characterId: string): void {
  db.prepare("DELETE FROM play_campaign_concentration WHERE campaign_id = ? AND character_id = ?").run(
    campaignId,
    characterId,
  );
}

function concentrationJson(row: PlayCampaignConcentrationRow | undefined) {
  if (!row) return null;
  return { spell_id: row.spell_id, target: row.target, remaining_turns: row.remaining_turns };
}

export function handlePutConcentration(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterCasterRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.spell_id !== "string" ||
    body.spell_id.length === 0 ||
    typeof body.target !== "string" ||
    body.target.length === 0 ||
    typeof body.duration_turns !== "number" ||
    !Number.isFinite(body.duration_turns)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!SPELLCASTING_ABILITY_COLUMN[character.class]) {
    sendJson(res, 400, { error: "not a spellcaster" });
    return;
  }

  if (!hasPlayCampaignSpell(campaignId, characterId, body.spell_id)) {
    sendJson(res, 400, { error: "unknown spell" });
    return;
  }

  const preparedSpells = getPlayCampaignPreparedSpells(campaignId, characterId);
  if (!preparedSpells.includes(body.spell_id)) {
    sendJson(res, 400, { error: "spell not prepared" });
    return;
  }

  if (body.duration_turns < 1) {
    sendJson(res, 400, { error: "invalid duration" });
    return;
  }

  db.prepare(
    `INSERT INTO play_campaign_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?)
     ON CONFLICT (campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns`,
  ).run(campaignId, characterId, body.spell_id, body.target, body.duration_turns);

  sendJson(res, 200, {
    character_id: characterId,
    concentration: { spell_id: body.spell_id, target: body.target, remaining_turns: body.duration_turns },
  });
}

export function handleGetConcentration(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const character = getPlayCampaignCharacterCasterRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  const row = getPlayCampaignConcentration(campaignId, characterId);
  sendJson(res, 200, { character_id: characterId, concentration: concentrationJson(row) });
}

export function handleAdvanceConcentrationTurn(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const character = getPlayCampaignCharacterCasterRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  const row = getPlayCampaignConcentration(campaignId, characterId);
  if (!row) {
    sendJson(res, 200, { character_id: characterId, concentration: null });
    return;
  }

  const remainingTurns = row.remaining_turns - 1;
  if (remainingTurns <= 0) {
    clearPlayCampaignConcentration(campaignId, characterId);
    sendJson(res, 200, { character_id: characterId, concentration: null });
    return;
  }

  db.prepare(
    "UPDATE play_campaign_concentration SET remaining_turns = ? WHERE campaign_id = ? AND character_id = ?",
  ).run(remainingTurns, campaignId, characterId);

  sendJson(res, 200, {
    character_id: characterId,
    concentration: { spell_id: row.spell_id, target: row.target, remaining_turns: remainingTurns },
  });
}

export function handleDeleteConcentration(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterCasterRow(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  clearPlayCampaignConcentration(campaignId, characterId);
  sendJson(res, 200, { character_id: characterId, concentration: null });
}

// --- Inventory item stacks ---------------------------------------------

const VALID_INVENTORY_ITEM_IDS = new Set([
  "healing-potion",
  "torch",
  "leather-armor",
  "ring-of-protection",
  "amulet-of-health",
]);

const EQUIPMENT_SLOTS = new Set(["armor", "accessory"]);

const EQUIPMENT_ITEM_SLOT: Record<string, string> = {
  "leather-armor": "armor",
  "ring-of-protection": "accessory",
  "amulet-of-health": "accessory",
};

const ATTUNABLE_ITEM_IDS = new Set(["ring-of-protection", "amulet-of-health"]);

const MAX_ATTUNEMENTS = 1;

function getPlayCampaignInventoryQuantity(campaignId: string, characterId: string, itemId: string): number {
  const row = db
    .prepare(
      "SELECT quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
    )
    .get(campaignId, characterId, itemId) as { quantity: number } | undefined;
  return row ? row.quantity : 0;
}

export function handleAddInventoryItemStack(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.item_id !== "string" ||
    !VALID_INVENTORY_ITEM_IDS.has(body.item_id) ||
    typeof body.quantity !== "number" ||
    !Number.isInteger(body.quantity) ||
    body.quantity <= 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const currentQuantity = getPlayCampaignInventoryQuantity(campaignId, characterId, body.item_id);
  const totalQuantity = currentQuantity + body.quantity;

  db.prepare(
    `INSERT INTO play_campaign_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity`,
  ).run(campaignId, characterId, body.item_id, totalQuantity);

  sendJson(res, 201, {
    character_id: characterId,
    item_id: body.item_id,
    quantity: body.quantity,
    total_quantity: totalQuantity,
  });
}

export function handleGetInventoryItemStacks(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  const items = db
    .prepare(
      "SELECT item_id, quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? ORDER BY item_id ASC",
    )
    .all(campaignId, characterId) as { item_id: string; quantity: number }[];

  sendJson(res, 200, {
    character_id: characterId,
    items: items.map((item) => ({ item_id: item.item_id, quantity: item.quantity })),
  });
}

export function handleRemoveInventoryItemStack(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  itemId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !VALID_INVENTORY_ITEM_IDS.has(itemId) ||
    !isPlainObject(body) ||
    typeof body.quantity !== "number" ||
    !Number.isInteger(body.quantity) ||
    body.quantity <= 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const currentQuantity = getPlayCampaignInventoryQuantity(campaignId, characterId, itemId);
  if (body.quantity > currentQuantity) {
    sendJson(res, 409, { error: "insufficient quantity" });
    return;
  }

  const remainingQuantity = currentQuantity - body.quantity;
  if (remainingQuantity === 0) {
    db.prepare("DELETE FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?").run(
      campaignId,
      characterId,
      itemId,
    );
  } else {
    db.prepare(
      "UPDATE play_campaign_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
    ).run(remainingQuantity, campaignId, characterId, itemId);
  }

  sendJson(res, 200, {
    character_id: characterId,
    item_id: itemId,
    quantity: body.quantity,
    total_quantity: remainingQuantity,
  });
}

// --- Equipment and attunement -------------------------------------------

interface PlayCampaignEquipmentRow {
  item_id: string;
  attuned: number;
}

function getPlayCampaignEquipment(
  campaignId: string,
  characterId: string,
  slot: string,
): PlayCampaignEquipmentRow | undefined {
  return db
    .prepare(
      "SELECT item_id, attuned FROM play_campaign_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?",
    )
    .get(campaignId, characterId, slot) as PlayCampaignEquipmentRow | undefined;
}

function countPlayCampaignAttunements(campaignId: string, characterId: string): number {
  const row = db
    .prepare(
      "SELECT COUNT(*) AS count FROM play_campaign_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
    )
    .get(campaignId, characterId) as { count: number };
  return row.count;
}

export function handleEquipItem(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  slot: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!EQUIPMENT_SLOTS.has(slot)) {
    sendJson(res, 400, { error: "invalid slot" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.item_id !== "string" ||
    !VALID_INVENTORY_ITEM_IDS.has(body.item_id)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (EQUIPMENT_ITEM_SLOT[body.item_id] !== slot) {
    sendJson(res, 400, { error: "item does not match slot" });
    return;
  }

  const heldQuantity = getPlayCampaignInventoryQuantity(campaignId, characterId, body.item_id);
  if (heldQuantity <= 0) {
    sendJson(res, 400, { error: "item not held" });
    return;
  }

  db.prepare(
    `INSERT INTO play_campaign_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, 0)
     ON CONFLICT (campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0`,
  ).run(campaignId, characterId, slot, body.item_id);

  sendJson(res, 200, {
    character_id: characterId,
    slot,
    item_id: body.item_id,
    attuned: false,
  });
}

export function handleGetEquipment(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  slot: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (!EQUIPMENT_SLOTS.has(slot)) {
    sendJson(res, 400, { error: "invalid slot" });
    return;
  }

  const equipment = getPlayCampaignEquipment(campaignId, characterId, slot);

  sendJson(res, 200, {
    character_id: characterId,
    slot,
    item_id: equipment ? equipment.item_id : "",
    attuned: equipment ? equipment.attuned === 1 : false,
  });
}

export function handleAttuneEquipment(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  slot: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!EQUIPMENT_SLOTS.has(slot)) {
    sendJson(res, 400, { error: "invalid slot" });
    return;
  }

  const equipment = getPlayCampaignEquipment(campaignId, characterId, slot);
  if (!equipment || !ATTUNABLE_ITEM_IDS.has(equipment.item_id)) {
    sendJson(res, 400, { error: "slot does not contain an attunable item" });
    return;
  }

  if (equipment.attuned === 1) {
    sendJson(res, 409, { error: "item already attuned" });
    return;
  }

  const attunementCount = countPlayCampaignAttunements(campaignId, characterId);
  if (attunementCount >= MAX_ATTUNEMENTS) {
    sendJson(res, 409, { error: "max attunements reached" });
    return;
  }

  db.prepare(
    "UPDATE play_campaign_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?",
  ).run(campaignId, characterId, slot);

  sendJson(res, 200, {
    character_id: characterId,
    slot,
    item_id: equipment.item_id,
    attuned: true,
    attunement_count: attunementCount + 1,
    max_attunements: MAX_ATTUNEMENTS,
  });
}

// --- Consumables ---------------------------------------------------------

const CONSUMABLE_ITEM_IDS = new Set(["healing-potion"]);

const CONSUMABLE_EFFECTS: Record<string, { type: string; hp_restored: number }> = {
  "healing-potion": { type: "healing", hp_restored: 5 },
};

export function handleConsumeInventoryItem(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  itemId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!VALID_INVENTORY_ITEM_IDS.has(itemId) || !CONSUMABLE_ITEM_IDS.has(itemId)) {
    sendJson(res, 400, { error: "item is not consumable" });
    return;
  }

  const currentQuantity = getPlayCampaignInventoryQuantity(campaignId, characterId, itemId);
  if (currentQuantity <= 0) {
    sendJson(res, 409, { error: "no held stack of item" });
    return;
  }

  const remainingQuantity = currentQuantity - 1;
  if (remainingQuantity === 0) {
    db.prepare("DELETE FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?").run(
      campaignId,
      characterId,
      itemId,
    );
  } else {
    db.prepare(
      "UPDATE play_campaign_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
    ).run(remainingQuantity, campaignId, characterId, itemId);
  }

  sendJson(res, 200, {
    character_id: characterId,
    item_id: itemId,
    quantity_consumed: 1,
    total_quantity: remainingQuantity,
    effect: CONSUMABLE_EFFECTS[itemId],
  });
}

// --- Currency and trade ----------------------------------------------------

interface PlayCampaignGoldRow {
  gold: number;
}

function getPlayCampaignCharacterGold(campaignId: string, characterId: string): number | undefined {
  const row = db
    .prepare("SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?")
    .get(campaignId, characterId) as PlayCampaignGoldRow | undefined;
  return row ? row.gold : undefined;
}

function nextPlayCampaignTransferId(campaignId: string): number {
  const row = db
    .prepare("SELECT MAX(transfer_id) AS max_transfer_id FROM play_campaign_transfers WHERE campaign_id = ?")
    .get(campaignId) as { max_transfer_id: number | null };
  return (row.max_transfer_id ?? 0) + 1;
}

export function handleGetCharacterCurrency(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const gold = getPlayCampaignCharacterGold(campaignId, characterId);
  if (gold === undefined) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  sendJson(res, 200, { character_id: characterId, gold });
}

export function handleTransferCharacterCurrency(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.to_character_id !== "string" ||
    body.to_character_id.length === 0 ||
    typeof body.gold !== "number" ||
    !Number.isInteger(body.gold)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const toCharacterId = body.to_character_id;
  const goldAmount = body.gold;

  if (toCharacterId === characterId || goldAmount <= 0 || !hasPlayCampaignCharacter(campaignId, toCharacterId)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const fromGold = getPlayCampaignCharacterGold(campaignId, characterId);
  const toGold = getPlayCampaignCharacterGold(campaignId, toCharacterId);
  if (fromGold === undefined || toGold === undefined) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (fromGold < goldAmount) {
    sendJson(res, 409, { error: "insufficient gold" });
    return;
  }

  const newFromGold = fromGold - goldAmount;
  const newToGold = toGold + goldAmount;

  db.prepare("UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?").run(
    newFromGold,
    campaignId,
    characterId,
  );
  db.prepare("UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?").run(
    newToGold,
    campaignId,
    toCharacterId,
  );

  const transferId = nextPlayCampaignTransferId(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, transferId, characterId, toCharacterId, goldAmount);

  sendJson(res, 201, {
    from_character_id: characterId,
    to_character_id: toCharacterId,
    gold: goldAmount,
    from_gold: newFromGold,
    to_gold: newToGold,
    transfer_id: transferId,
  });
}

// --- Loot distribution -------------------------------------------------

interface PlayCampaignLootRow {
  loot_id: string;
  item_id: string;
  quantity: number;
  status: string;
  recipient_character_id: string | null;
}

function getPlayCampaignLoot(campaignId: string, lootId: string): PlayCampaignLootRow | undefined {
  return db
    .prepare(
      "SELECT loot_id, item_id, quantity, status, recipient_character_id FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
    )
    .get(campaignId, lootId) as PlayCampaignLootRow | undefined;
}

export function handleCreateLoot(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.loot_id !== "string" ||
    body.loot_id.length === 0 ||
    typeof body.item_id !== "string" ||
    !VALID_INVENTORY_ITEM_IDS.has(body.item_id) ||
    typeof body.quantity !== "number" ||
    !Number.isInteger(body.quantity) ||
    body.quantity <= 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayCampaignLoot(campaignId, body.loot_id)) {
    sendJson(res, 409, { error: "loot already exists" });
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status, recipient_character_id) VALUES (?, ?, ?, ?, 'open', NULL)",
  ).run(campaignId, body.loot_id, body.item_id, body.quantity);

  sendJson(res, 201, {
    loot_id: body.loot_id,
    item_id: body.item_id,
    quantity: body.quantity,
    status: "open",
  });
}

export function handleVoteLoot(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  lootId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (actor.role !== "player" || !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const loot = getPlayCampaignLoot(campaignId, lootId);
  if (!loot) {
    sendJson(res, 404, { error: "loot not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.recipient_character_id !== "string" ||
    body.recipient_character_id.length === 0 ||
    !hasPlayCampaignCharacter(campaignId, body.recipient_character_id)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existingVote = db
    .prepare(
      "SELECT recipient_character_id FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND voter = ?",
    )
    .get(campaignId, lootId, actor.username);
  if (existingVote) {
    sendJson(res, 409, { error: "vote already cast" });
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)",
  ).run(campaignId, lootId, actor.username, body.recipient_character_id);

  const votesForRecipient = (
    db
      .prepare(
        "SELECT COUNT(*) AS count FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
      )
      .get(campaignId, lootId, body.recipient_character_id) as { count: number }
  ).count;

  sendJson(res, 201, {
    loot_id: lootId,
    voter: actor.username,
    recipient_character_id: body.recipient_character_id,
    votes_for_recipient: votesForRecipient,
  });
}

function highestPlayCampaignLootVote(
  campaignId: string,
  lootId: string,
): { recipientId: string; votes: number } | "tied" | undefined {
  const rows = db
    .prepare(
      "SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY votes DESC",
    )
    .all(campaignId, lootId) as { recipient_character_id: string; votes: number }[];
  if (rows.length === 0) return undefined;
  if (rows.length > 1 && rows[0].votes === rows[1].votes) return "tied";
  return { recipientId: rows[0].recipient_character_id, votes: rows[0].votes };
}

export function handleAssignLoot(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  lootId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const loot = getPlayCampaignLoot(campaignId, lootId);
  if (!loot) {
    sendJson(res, 404, { error: "loot not found" });
    return;
  }

  if (loot.status !== "open") {
    sendJson(res, 409, { error: "loot is not open" });
    return;
  }

  const winner = highestPlayCampaignLootVote(campaignId, lootId);
  if (!winner || winner === "tied") {
    sendJson(res, 409, { error: "no unambiguous vote winner" });
    return;
  }

  const currentQuantity = getPlayCampaignInventoryQuantity(campaignId, winner.recipientId, loot.item_id);
  const totalQuantity = currentQuantity + loot.quantity;

  db.prepare(
    `INSERT INTO play_campaign_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity`,
  ).run(campaignId, winner.recipientId, loot.item_id, totalQuantity);

  db.prepare(
    "UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?",
  ).run(winner.recipientId, campaignId, lootId);

  sendJson(res, 200, {
    loot_id: lootId,
    recipient_character_id: winner.recipientId,
    item_id: loot.item_id,
    quantity: loot.quantity,
    votes: winner.votes,
    status: "assigned",
  });
}

export function handleGetLoot(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  lootId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const loot = getPlayCampaignLoot(campaignId, lootId);
  if (!loot) {
    sendJson(res, 404, { error: "loot not found" });
    return;
  }

  const voteRows = db
    .prepare(
      "SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id",
    )
    .all(campaignId, lootId) as { recipient_character_id: string; votes: number }[];
  const votes: Record<string, number> = {};
  for (const row of voteRows) {
    votes[row.recipient_character_id] = row.votes;
  }

  sendJson(res, 200, {
    loot_id: loot.loot_id,
    item_id: loot.item_id,
    quantity: loot.quantity,
    status: loot.status,
    recipient_character_id: loot.recipient_character_id,
    votes,
  });
}

// --- NPC agendas ---------------------------------------------------------

interface PlayCampaignNpcRow {
  npc_id: string;
  name: string;
  agenda: string;
  public_status: string;
}

function getPlayCampaignNpc(campaignId: string, npcId: string): PlayCampaignNpcRow | undefined {
  return db
    .prepare(
      "SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
    )
    .get(campaignId, npcId) as PlayCampaignNpcRow | undefined;
}

export function handleCreatePlayNpc(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.npc_id !== "string" ||
    body.npc_id.length === 0 ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    typeof body.agenda !== "string" ||
    body.agenda.length === 0 ||
    typeof body.public_status !== "string" ||
    body.public_status.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayCampaignNpc(campaignId, body.npc_id)) {
    sendJson(res, 409, { error: "npc already exists" });
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, body.npc_id, body.name, body.agenda, body.public_status);

  sendJson(res, 201, {
    npc_id: body.npc_id,
    name: body.name,
    agenda: body.agenda,
    public_status: body.public_status,
  });
}

export function handleUpdatePlayNpcAgenda(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  npcId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const npc = getPlayCampaignNpc(campaignId, npcId);
  if (!npc) {
    sendJson(res, 404, { error: "npc not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.agenda !== "string" ||
    body.agenda.length === 0 ||
    typeof body.public_status !== "string" ||
    body.public_status.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  db.prepare(
    "UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?",
  ).run(body.agenda, body.public_status, campaignId, npcId);

  sendJson(res, 200, {
    npc_id: npc.npc_id,
    name: npc.name,
    agenda: body.agenda,
    public_status: body.public_status,
  });
}

export function handleGetPlayNpc(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  npcId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const npc = getPlayCampaignNpc(campaignId, npcId);
  if (!npc) {
    sendJson(res, 404, { error: "npc not found" });
    return;
  }

  if (actor.username === campaign.owner) {
    sendJson(res, 200, {
      npc_id: npc.npc_id,
      name: npc.name,
      agenda: npc.agenda,
      public_status: npc.public_status,
    });
    return;
  }

  sendJson(res, 200, {
    npc_id: npc.npc_id,
    name: npc.name,
    public_status: npc.public_status,
  });
}

// --- Faction reputation ---------------------------------------------------

interface PlayFactionRow {
  faction_id: string;
  name: string;
}

function getPlayFaction(campaignId: string, factionId: string): PlayFactionRow | undefined {
  return db
    .prepare("SELECT faction_id, name FROM play_campaign_play_factions WHERE campaign_id = ? AND faction_id = ?")
    .get(campaignId, factionId) as PlayFactionRow | undefined;
}

const REPUTATION_MIN = -100;
const REPUTATION_MAX = 100;

export function handleCreatePlayFaction(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.faction_id !== "string" ||
    body.faction_id.length === 0 ||
    typeof body.name !== "string" ||
    body.name.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayFaction(campaignId, body.faction_id)) {
    sendJson(res, 409, { error: "faction already exists" });
    return;
  }

  db.prepare("INSERT INTO play_campaign_play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)").run(
    campaignId,
    body.faction_id,
    body.name,
  );

  sendJson(res, 201, { faction_id: body.faction_id, name: body.name });
}

export function handleChangePlayFactionReputation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  factionId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const faction = getPlayFaction(campaignId, factionId);
  if (!faction) {
    sendJson(res, 404, { error: "faction not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.character_id !== "string" ||
    !body.character_id ||
    !hasPlayCampaignCharacter(campaignId, body.character_id) ||
    typeof body.delta !== "number" ||
    !Number.isInteger(body.delta) ||
    body.delta === 0 ||
    body.delta < -25 ||
    body.delta > 25 ||
    typeof body.reason !== "string" ||
    body.reason.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = db
    .prepare(
      "SELECT reputation FROM play_campaign_faction_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ?",
    )
    .get(campaignId, factionId, body.character_id) as { reputation: number } | undefined;
  const currentReputation = existing?.reputation ?? 0;
  const nextReputation = Math.max(REPUTATION_MIN, Math.min(REPUTATION_MAX, currentReputation + body.delta));

  db.prepare(
    `INSERT INTO play_campaign_faction_reputation (campaign_id, faction_id, character_id, reputation)
     VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, faction_id, character_id)
     DO UPDATE SET reputation = excluded.reputation`,
  ).run(campaignId, factionId, body.character_id, nextReputation);

  const sequenceRow = db
    .prepare(
      "SELECT COALESCE(MAX(sequence), -1) AS max_sequence FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ?",
    )
    .get(campaignId, factionId) as { max_sequence: number };
  const sequence = sequenceRow.max_sequence + 1;

  db.prepare(
    `INSERT INTO play_campaign_faction_reputation_history
       (campaign_id, faction_id, sequence, character_id, reputation, delta, reason)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(campaignId, factionId, sequence, body.character_id, nextReputation, body.delta, body.reason);

  sendJson(res, 201, {
    faction_id: factionId,
    character_id: body.character_id,
    reputation: nextReputation,
    delta: body.delta,
    reason: body.reason,
  });
}

export function handleGetPlayFactionReputation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  factionId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const faction = getPlayFaction(campaignId, factionId);
  if (!faction) {
    sendJson(res, 404, { error: "faction not found" });
    return;
  }

  const rows = db
    .prepare(
      "SELECT character_id, reputation, delta, reason FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId, factionId) as { character_id: string; reputation: number; delta: number; reason: string }[];

  let entries = rows;
  if (actor.username !== campaign.owner) {
    const ownCharacter = getPlayCampaignMemberCharacter(campaignId, actor.username);
    const ownCharacterId = ownCharacter?.character_id;
    entries = rows.filter((row) => row.character_id === ownCharacterId);
  }

  sendJson(res, 200, {
    faction_id: factionId,
    entries: entries.map((entry) => ({
      faction_id: factionId,
      character_id: entry.character_id,
      reputation: entry.reputation,
      delta: entry.delta,
      reason: entry.reason,
    })),
  });
}

// --- NPC dialogue -----------------------------------------------------------

interface PlayNpcDialogueRow {
  dialogue_id: string;
  speaker: string;
  text: string;
  visibility: string;
}

function getPlayNpcDialogueEntries(campaignId: string, npcId: string): PlayNpcDialogueRow[] {
  return db
    .prepare(
      "SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId, npcId) as unknown as PlayNpcDialogueRow[];
}

export function handleCreatePlayNpcDialogue(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  npcId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const npc = getPlayCampaignNpc(campaignId, npcId);
  if (!npc) {
    sendJson(res, 404, { error: "npc not found" });
    return;
  }

  if (actor.username !== campaign.owner) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.dialogue_id !== "string" ||
    body.dialogue_id.length === 0 ||
    typeof body.speaker !== "string" ||
    body.speaker.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0 ||
    (body.visibility !== "public" && body.visibility !== "private")
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = db
    .prepare(
      "SELECT dialogue_id FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?",
    )
    .get(campaignId, npcId, body.dialogue_id);
  if (existing) {
    sendJson(res, 409, { error: "dialogue already exists" });
    return;
  }

  const sequenceRow = db
    .prepare(
      "SELECT COALESCE(MAX(sequence), -1) AS max_sequence FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ?",
    )
    .get(campaignId, npcId) as { max_sequence: number };
  const sequence = sequenceRow.max_sequence + 1;

  db.prepare(
    `INSERT INTO play_campaign_npc_dialogue
       (campaign_id, npc_id, sequence, dialogue_id, speaker, text, visibility)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(campaignId, npcId, sequence, body.dialogue_id, body.speaker, body.text, body.visibility);

  sendJson(res, 201, {
    dialogue_id: body.dialogue_id,
    speaker: body.speaker,
    text: body.text,
    visibility: body.visibility,
  });
}

export function handleGetPlayNpcDialogue(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  npcId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const npc = getPlayCampaignNpc(campaignId, npcId);
  if (!npc) {
    sendJson(res, 404, { error: "npc not found" });
    return;
  }

  const entries = getPlayNpcDialogueEntries(campaignId, npcId);
  const visibleEntries = actor.username === campaign.owner ? entries : entries.filter((e) => e.visibility === "public");

  sendJson(res, 200, {
    npc_id: npcId,
    entries: visibleEntries.map((entry) => ({
      dialogue_id: entry.dialogue_id,
      speaker: entry.speaker,
      text: entry.text,
      visibility: entry.visibility,
    })),
  });
}

// --- Relationship graph ------------------------------------------------------

interface PlayRelationshipRow {
  source_id: string;
  target_id: string;
  kind: string;
  score: number;
}

function isPlayCampaignEntity(campaignId: string, entityId: string): boolean {
  return hasPlayCampaignCharacter(campaignId, entityId) || getPlayCampaignNpc(campaignId, entityId) !== undefined;
}

function getPlayRelationship(
  campaignId: string,
  sourceId: string,
  targetId: string,
  kind: string,
): PlayRelationshipRow | undefined {
  return db
    .prepare(
      "SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
    )
    .get(campaignId, sourceId, targetId, kind) as PlayRelationshipRow | undefined;
}

export function handleCreatePlayRelationship(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.source_id !== "string" ||
    body.source_id.length === 0 ||
    typeof body.target_id !== "string" ||
    body.target_id.length === 0 ||
    typeof body.kind !== "string" ||
    body.kind.length === 0 ||
    !isValidInt(body.score, -100, 100)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (body.source_id === body.target_id) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!isPlayCampaignEntity(campaignId, body.source_id) || !isPlayCampaignEntity(campaignId, body.target_id)) {
    sendJson(res, 404, { error: "campaign entity not found" });
    return;
  }

  if (getPlayRelationship(campaignId, body.source_id, body.target_id, body.kind)) {
    sendJson(res, 409, { error: "relationship already exists" });
    return;
  }

  const sequenceRow = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) AS max_sequence FROM play_campaign_relationships WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number };
  const sequence = sequenceRow.max_sequence + 1;

  db.prepare(
    `INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score, sequence)
     VALUES (?, ?, ?, ?, ?, ?)`,
  ).run(campaignId, body.source_id, body.target_id, body.kind, body.score, sequence);

  sendJson(res, 201, {
    source_id: body.source_id,
    target_id: body.target_id,
    kind: body.kind,
    score: body.score,
  });
}

export function handleUpdatePlayRelationship(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  sourceId: string,
  targetId: string,
  kind: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const relationship = getPlayRelationship(campaignId, sourceId, targetId, kind);
  if (!relationship) {
    sendJson(res, 404, { error: "relationship not found" });
    return;
  }

  if (!isPlainObject(body) || !isValidInt(body.score, -100, 100)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  db.prepare(
    "UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
  ).run(body.score, campaignId, sourceId, targetId, kind);

  sendJson(res, 200, {
    source_id: sourceId,
    target_id: targetId,
    kind,
    score: body.score,
  });
}

export function handleGetPlayRelationships(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayRelationshipRow[];

  sendJson(res, 200, {
    edges: rows.map((row) => ({
      source_id: row.source_id,
      target_id: row.target_id,
      kind: row.kind,
      score: row.score,
    })),
  });
}

// --- Campaign clues ----------------------------------------------------------

const CLUE_AUDIENCES = new Set(["character", "party", "hidden"]);

interface PlayClueRow {
  clue_id: string;
  sequence: number;
  text: string;
  audience: string;
  character_id: string | null;
}

function hasPlayClue(campaignId: string, clueId: string): boolean {
  const row = db
    .prepare("SELECT 1 FROM play_campaign_clues WHERE campaign_id = ? AND clue_id = ?")
    .get(campaignId, clueId);
  return row !== undefined;
}

function clueResponseShape(row: PlayClueRow): Record<string, unknown> {
  const shape: Record<string, unknown> = {
    clue_id: row.clue_id,
    text: row.text,
    audience: row.audience,
  };
  if (row.audience === "character") {
    shape.character_id = row.character_id;
  }
  return shape;
}

export function handleCreatePlayClue(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.clue_id !== "string" ||
    body.clue_id.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0 ||
    typeof body.audience !== "string" ||
    !CLUE_AUDIENCES.has(body.audience)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (body.audience === "character") {
    if (typeof body.character_id !== "string" || body.character_id.length === 0) {
      sendJson(res, 400, { error: "invalid request" });
      return;
    }
    if (!hasPlayCampaignCharacter(campaignId, body.character_id)) {
      sendJson(res, 400, { error: "unknown character" });
      return;
    }
  } else if (body.character_id !== undefined) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasPlayClue(campaignId, body.clue_id)) {
    sendJson(res, 409, { error: "clue already exists" });
    return;
  }

  const sequenceRow = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) AS max_sequence FROM play_campaign_clues WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number };
  const sequence = sequenceRow.max_sequence + 1;

  const characterId = body.audience === "character" ? (body.character_id as string) : null;

  db.prepare(
    `INSERT INTO play_campaign_clues (campaign_id, clue_id, sequence, text, audience, character_id)
     VALUES (?, ?, ?, ?, ?, ?)`,
  ).run(campaignId, body.clue_id, sequence, body.text, body.audience, characterId);

  sendJson(
    res,
    201,
    clueResponseShape({
      clue_id: body.clue_id,
      sequence,
      text: body.text,
      audience: body.audience,
      character_id: characterId,
    }),
  );
}

export function handleGetPlayClues(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT clue_id, sequence, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayClueRow[];

  let visibleRows: PlayClueRow[];
  if (actor.username === campaign.owner) {
    visibleRows = rows;
  } else {
    const member = getPlayCampaignMemberCharacter(campaignId, actor.username);
    const ownCharacterId = member?.character_id;
    visibleRows = rows.filter(
      (row) =>
        row.audience === "party" ||
        (row.audience === "character" && row.character_id === ownCharacterId),
    );
  }

  sendJson(res, 200, {
    clues: visibleRows.map((row) => clueResponseShape(row)),
  });
}

// --- Campaign quests ----------------------------------------------------------

interface PlayQuestRow {
  quest_id: string;
  sequence: number;
  title: string;
  depends_on: string;
  state: string;
}

function getPlayQuest(campaignId: string, questId: string): PlayQuestRow | undefined {
  return db
    .prepare("SELECT quest_id, sequence, title, depends_on, state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?")
    .get(campaignId, questId) as PlayQuestRow | undefined;
}

function hasPlayQuest(campaignId: string, questId: string): boolean {
  return getPlayQuest(campaignId, questId) !== undefined;
}

function questResponseShape(row: PlayQuestRow): Record<string, unknown> {
  return {
    quest_id: row.quest_id,
    title: row.title,
    depends_on: JSON.parse(row.depends_on) as string[],
    state: row.state,
  };
}

export function handleCreatePlayQuest(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.quest_id !== "string" ||
    body.quest_id.length === 0 ||
    typeof body.title !== "string" ||
    body.title.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (body.depends_on !== undefined && !Array.isArray(body.depends_on)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const dependsOn = (body.depends_on ?? []) as unknown[];
  if (!dependsOn.every((item) => typeof item === "string" && item.length > 0)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }
  const dependsOnStrings = dependsOn as string[];

  if (new Set(dependsOnStrings).size !== dependsOnStrings.length) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (dependsOnStrings.includes(body.quest_id)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!dependsOnStrings.every((dep) => hasPlayQuest(campaignId, dep))) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasPlayQuest(campaignId, body.quest_id)) {
    sendJson(res, 409, { error: "quest already exists" });
    return;
  }

  const sequenceRow = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) AS max_sequence FROM play_campaign_quests WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number };
  const sequence = sequenceRow.max_sequence + 1;

  db.prepare(
    `INSERT INTO play_campaign_quests (campaign_id, quest_id, sequence, title, depends_on, state)
     VALUES (?, ?, ?, ?, ?, ?)`,
  ).run(campaignId, body.quest_id, sequence, body.title, JSON.stringify(dependsOnStrings), "locked");

  sendJson(
    res,
    201,
    questResponseShape({
      quest_id: body.quest_id,
      sequence,
      title: body.title,
      depends_on: JSON.stringify(dependsOnStrings),
      state: "locked",
    }),
  );
}

export function handleUpdatePlayQuestState(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  questId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const quest = getPlayQuestWithRewards(campaignId, questId);
  if (!quest) {
    sendJson(res, 404, { error: "quest not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.state !== "string" ||
    (body.state !== "active" && body.state !== "completed")
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const dependsOn = JSON.parse(quest.depends_on) as string[];

  if (body.state === "active") {
    if (quest.state !== "locked") {
      sendJson(res, 409, { error: "invalid transition" });
      return;
    }
    const allDepsCompleted = dependsOn.every((dep) => {
      const depQuest = getPlayQuest(campaignId, dep);
      return depQuest?.state === "completed";
    });
    if (!allDepsCompleted) {
      sendJson(res, 409, { error: "invalid transition" });
      return;
    }
  } else {
    if (quest.state !== "active") {
      sendJson(res, 409, { error: "invalid transition" });
      return;
    }
  }

  db.prepare("UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?").run(
    body.state,
    campaignId,
    questId,
  );

  sendJson(
    res,
    200,
    questRewardsResponseShape({
      ...quest,
      state: body.state,
    }),
  );
}

export function handleGetPlayQuests(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT quest_id, sequence, title, depends_on, state FROM play_campaign_quests WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayQuestRow[];

  sendJson(res, 200, {
    quests: rows.map((row) => questResponseShape(row)),
  });
}

// --- Quest rewards --------------------------------------------------------

interface PlayQuestRewardsRow extends PlayQuestRow {
  rewards_xp: number | null;
  rewards_items: string | null;
  rewards_awarded: number;
}

function getPlayQuestWithRewards(campaignId: string, questId: string): PlayQuestRewardsRow | undefined {
  return db
    .prepare(
      "SELECT quest_id, sequence, title, depends_on, state, rewards_xp, rewards_items, rewards_awarded FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
    )
    .get(campaignId, questId) as PlayQuestRewardsRow | undefined;
}

function questRewardsResponseShape(row: PlayQuestRewardsRow): Record<string, unknown> {
  const base = questResponseShape(row);
  if (row.rewards_xp === null || row.rewards_items === null) {
    return base;
  }
  return {
    ...base,
    rewards: {
      xp: row.rewards_xp,
      items: JSON.parse(row.rewards_items) as Record<string, number>,
    },
  };
}

function grantPlayCampaignRewards(
  campaignId: string,
  characterId: string,
  xp: number,
  items: Record<string, number>,
): void {
  const row = db
    .prepare("SELECT xp, items FROM play_campaign_reward_grants WHERE campaign_id = ? AND character_id = ?")
    .get(campaignId, characterId) as { xp: number; items: string } | undefined;

  const currentXp = row ? row.xp : 0;
  const currentItems: Record<string, number> = row ? (JSON.parse(row.items) as Record<string, number>) : {};

  for (const [itemId, quantity] of Object.entries(items)) {
    currentItems[itemId] = (currentItems[itemId] ?? 0) + quantity;
  }

  db.prepare(
    `INSERT INTO play_campaign_reward_grants (campaign_id, character_id, xp, items) VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, character_id) DO UPDATE SET xp = excluded.xp, items = excluded.items`,
  ).run(campaignId, characterId, currentXp + xp, JSON.stringify(currentItems));

  for (const [itemId, quantity] of Object.entries(items)) {
    const currentQuantity = getPlayCampaignInventoryQuantity(campaignId, characterId, itemId);
    const newQuantity = currentQuantity + quantity;
    db.prepare(
      `INSERT INTO play_campaign_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
       ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity`,
    ).run(campaignId, characterId, itemId, newQuantity);
  }
}

export function handleConfigureQuestRewards(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  questId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const quest = getPlayQuestWithRewards(campaignId, questId);
  if (!quest) {
    sendJson(res, 404, { error: "quest not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    !isValidInt(body.xp, 0, Number.MAX_SAFE_INTEGER) ||
    !isPlainObject(body.items) ||
    !Object.entries(body.items).every(
      ([itemId, quantity]) =>
        VALID_INVENTORY_ITEM_IDS.has(itemId) && isValidInt(quantity, 1, Number.MAX_SAFE_INTEGER),
    )
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (quest.state !== "locked" && quest.state !== "active") {
    sendJson(res, 409, { error: "invalid state" });
    return;
  }

  const items = body.items as Record<string, number>;

  db.prepare(
    "UPDATE play_campaign_quests SET rewards_xp = ?, rewards_items = ? WHERE campaign_id = ? AND quest_id = ?",
  ).run(body.xp, JSON.stringify(items), campaignId, questId);

  sendJson(
    res,
    200,
    questRewardsResponseShape({
      ...quest,
      rewards_xp: body.xp,
      rewards_items: JSON.stringify(items),
    }),
  );
}

export function handleAwardQuestRewards(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  questId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const quest = getPlayQuestWithRewards(campaignId, questId);
  if (!quest) {
    sendJson(res, 404, { error: "quest not found" });
    return;
  }

  if (
    quest.state !== "completed" ||
    quest.rewards_xp === null ||
    quest.rewards_items === null ||
    quest.rewards_awarded
  ) {
    sendJson(res, 409, { error: "invalid state" });
    return;
  }

  const items = JSON.parse(quest.rewards_items) as Record<string, number>;
  const members = playCampaignMemberSummaries(campaignId);

  for (const member of members) {
    grantPlayCampaignRewards(campaignId, member.character_id, quest.rewards_xp, items);
  }

  db.prepare("UPDATE play_campaign_quests SET rewards_awarded = 1 WHERE campaign_id = ? AND quest_id = ?").run(
    campaignId,
    questId,
  );

  sendJson(res, 201, {
    quest_id: quest.quest_id,
    awarded: true,
    xp: quest.rewards_xp,
    items,
  });
}

export function handleGetCharacterRewards(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (!hasPlayCampaignCharacter(campaignId, characterId)) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  const row = db
    .prepare("SELECT xp, items FROM play_campaign_reward_grants WHERE campaign_id = ? AND character_id = ?")
    .get(campaignId, characterId) as { xp: number; items: string } | undefined;

  sendJson(res, 200, {
    character_id: characterId,
    xp: row ? row.xp : 0,
    items: row ? (JSON.parse(row.items) as Record<string, number>) : {},
  });
}

// --- World events ------------------------------------------------------

interface PlayWorldEventRow {
  event_id: string;
  sequence: number;
  turn_number: number;
  title: string;
  text: string;
  status: string;
  resolution_turn_number: number | null;
  resolution_text: string | null;
}

function getPlayWorldEvent(campaignId: string, eventId: string): PlayWorldEventRow | undefined {
  return db
    .prepare(
      `SELECT event_id, sequence, turn_number, title, text, status, resolution_turn_number, resolution_text
       FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?`,
    )
    .get(campaignId, eventId) as PlayWorldEventRow | undefined;
}

function nextPlayWorldEventSequence(campaignId: string): number {
  const row = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) AS max_sequence FROM play_campaign_world_events WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function worldEventResponseShape(row: PlayWorldEventRow): Record<string, unknown> {
  const base: Record<string, unknown> = {
    event_id: row.event_id,
    turn_number: row.turn_number,
    title: row.title,
    text: row.text,
    status: row.status,
  };
  if (row.status === "resolved") {
    base.resolution = {
      turn_number: row.resolution_turn_number,
      text: row.resolution_text,
    };
  }
  return base;
}

export function handleCreatePlayWorldEvent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.event_id !== "string" ||
    body.event_id.length === 0 ||
    typeof body.title !== "string" ||
    body.title.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0 ||
    !isValidInt(body.turn_number, Number.MIN_SAFE_INTEGER, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const currentTurnNumber = campaign.turn_number ?? 0;
  if (body.turn_number < currentTurnNumber) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayWorldEvent(campaignId, body.event_id)) {
    sendJson(res, 409, { error: "event already exists" });
    return;
  }

  const sequence = nextPlayWorldEventSequence(campaignId);

  db.prepare(
    `INSERT INTO play_campaign_world_events (campaign_id, event_id, sequence, turn_number, title, text, status)
     VALUES (?, ?, ?, ?, ?, ?, 'scheduled')`,
  ).run(campaignId, body.event_id, sequence, body.turn_number, body.title, body.text);

  sendJson(
    res,
    201,
    worldEventResponseShape({
      event_id: body.event_id,
      sequence,
      turn_number: body.turn_number,
      title: body.title,
      text: body.text,
      status: "scheduled",
      resolution_turn_number: null,
      resolution_text: null,
    }),
  );
}

export function handleResolvePlayWorldEvent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  eventId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignTurn(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const event = getPlayWorldEvent(campaignId, eventId);
  if (!event) {
    sendJson(res, 404, { error: "event not found" });
    return;
  }

  if (!isPlainObject(body) || typeof body.text !== "string" || body.text.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (event.status === "resolved") {
    sendJson(res, 409, { error: "already resolved" });
    return;
  }

  const currentTurnNumber = campaign.turn_number ?? 0;
  if (currentTurnNumber !== event.turn_number) {
    sendJson(res, 409, { error: "turn mismatch" });
    return;
  }

  db.prepare(
    `UPDATE play_campaign_world_events
     SET status = 'resolved', resolution_turn_number = ?, resolution_text = ?
     WHERE campaign_id = ? AND event_id = ?`,
  ).run(event.turn_number, body.text, campaignId, eventId);

  sendJson(
    res,
    201,
    worldEventResponseShape({
      ...event,
      status: "resolved",
      resolution_turn_number: event.turn_number,
      resolution_text: body.text,
    }),
  );
}

export function handleGetPlayWorldEvents(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      `SELECT event_id, sequence, turn_number, title, text, status, resolution_turn_number, resolution_text
       FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, sequence ASC`,
    )
    .all(campaignId) as unknown as PlayWorldEventRow[];

  sendJson(res, 200, {
    events: rows.map((row) => worldEventResponseShape(row)),
  });
}

// --- Campaign calendar: DM-initialized, deterministic weather ---------------

const CALENDAR_SEASONS: Record<string, number> = { spring: 0, summer: 1, autumn: 2, winter: 3 };

function calendarWeather(day: number, season: string): string {
  const offset = CALENDAR_SEASONS[season];
  const index = (day + offset) % 4;
  return ["clear", "rain", "wind", "snow"][index];
}

interface PlayCampaignCalendarRow {
  owner: string;
  calendar_day: number | null;
  calendar_season: string | null;
}

function getPlayCampaignCalendar(id: string): PlayCampaignCalendarRow | undefined {
  return db.prepare("SELECT owner, calendar_day, calendar_season FROM play_campaigns WHERE id = ?").get(id) as
    | PlayCampaignCalendarRow
    | undefined;
}

export function handleInitPlayCampaignCalendar(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignCalendar(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    !isValidInt(body.day, 1, Number.MAX_SAFE_INTEGER) ||
    typeof body.season !== "string" ||
    !(body.season in CALENDAR_SEASONS)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (campaign.calendar_day !== null) {
    sendJson(res, 409, { error: "calendar already initialized" });
    return;
  }

  db.prepare("UPDATE play_campaigns SET calendar_day = ?, calendar_season = ? WHERE id = ?").run(
    body.day,
    body.season,
    campaignId,
  );

  sendJson(res, 201, { day: body.day, season: body.season, weather: calendarWeather(body.day, body.season) });
}

export function handleGetPlayCampaignCalendar(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignCalendar(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (campaign.calendar_day === null || campaign.calendar_season === null) {
    sendJson(res, 404, { error: "calendar not initialized" });
    return;
  }

  sendJson(res, 200, {
    day: campaign.calendar_day,
    season: campaign.calendar_season,
    weather: calendarWeather(campaign.calendar_day, campaign.calendar_season),
  });
}

export function handleAdvancePlayCampaignCalendar(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignCalendar(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isPlainObject(body) || !isValidInt(body.days, 1, 30)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (campaign.calendar_day === null || campaign.calendar_season === null) {
    sendJson(res, 404, { error: "calendar not initialized" });
    return;
  }

  const nextDay = campaign.calendar_day + body.days;
  db.prepare("UPDATE play_campaigns SET calendar_day = ? WHERE id = ?").run(nextDay, campaignId);

  sendJson(res, 200, {
    day: nextDay,
    season: campaign.calendar_season,
    weather: calendarWeather(nextDay, campaign.calendar_season),
  });
}

// --- Campaign settlements ----------------------------------------------------

const SETTLEMENT_AVAILABILITIES = new Set(["open", "limited", "closed"]);

interface PlaySettlementRow {
  settlement_id: string;
  sequence: number;
  name: string;
  services: string;
  availability: string;
  discovered_by: string;
}

function getPlaySettlement(campaignId: string, settlementId: string): PlaySettlementRow | undefined {
  return db
    .prepare(
      "SELECT settlement_id, sequence, name, services, availability, discovered_by FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
    )
    .get(campaignId, settlementId) as PlaySettlementRow | undefined;
}

function nextPlaySettlementSequence(campaignId: string): number {
  const row = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) AS max_sequence FROM play_campaign_settlements WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function parseSettlementServices(body: Record<string, unknown>): string[] | undefined {
  if (!Array.isArray(body.services) || body.services.length === 0) return undefined;
  const normalized: string[] = [];
  for (const entry of body.services) {
    if (typeof entry !== "string") return undefined;
    const trimmed = entry.trim();
    if (trimmed.length === 0) return undefined;
    if (normalized.includes(trimmed)) return undefined;
    normalized.push(trimmed);
  }
  return normalized;
}

function settlementResponseShape(row: PlaySettlementRow, viewer: Actor, campaignOwner: string, ownCharacterId: string | undefined): Record<string, unknown> {
  const discoveredBy = JSON.parse(row.discovered_by) as string[];
  const visibleDiscoveredBy =
    viewer.username === campaignOwner
      ? discoveredBy
      : discoveredBy.filter((characterId) => characterId === ownCharacterId);
  return {
    settlement_id: row.settlement_id,
    name: row.name,
    services: JSON.parse(row.services) as string[],
    availability: row.availability,
    discovered_by: visibleDiscoveredBy,
  };
}

export function handleCreatePlaySettlement(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.settlement_id !== "string" ||
    body.settlement_id.length === 0 ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    typeof body.availability !== "string" ||
    !SETTLEMENT_AVAILABILITIES.has(body.availability)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const services = parseSettlementServices(body);
  if (!services) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlaySettlement(campaignId, body.settlement_id)) {
    sendJson(res, 409, { error: "settlement already exists" });
    return;
  }

  const sequence = nextPlaySettlementSequence(campaignId);

  db.prepare(
    `INSERT INTO play_campaign_settlements (campaign_id, settlement_id, sequence, name, services, availability, discovered_by)
     VALUES (?, ?, ?, ?, ?, ?, '[]')`,
  ).run(campaignId, body.settlement_id, sequence, body.name, JSON.stringify(services), body.availability);

  sendJson(
    res,
    201,
    settlementResponseShape(
      {
        settlement_id: body.settlement_id,
        sequence,
        name: body.name,
        services: JSON.stringify(services),
        availability: body.availability,
        discovered_by: "[]",
      },
      actor,
      campaign.owner,
      undefined,
    ),
  );
}

export function handleUpdatePlaySettlement(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    sendJson(res, 404, { error: "settlement not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    typeof body.availability !== "string" ||
    !SETTLEMENT_AVAILABILITIES.has(body.availability)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const services = parseSettlementServices(body);
  if (!services) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  db.prepare(
    "UPDATE play_campaign_settlements SET name = ?, services = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?",
  ).run(body.name, JSON.stringify(services), body.availability, campaignId, settlementId);

  sendJson(
    res,
    200,
    settlementResponseShape(
      {
        ...settlement,
        name: body.name,
        services: JSON.stringify(services),
        availability: body.availability,
      },
      actor,
      campaign.owner,
      undefined,
    ),
  );
}

export function handleDiscoverPlaySettlement(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (actor.role !== "player" || !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    sendJson(res, 404, { error: "settlement not found" });
    return;
  }

  const member = getPlayCampaignMemberCharacter(campaignId, actor.username);
  const ownCharacterId = member?.character_id;

  const discoveredBy = JSON.parse(settlement.discovered_by) as string[];
  const alreadyDiscovered = ownCharacterId !== undefined && discoveredBy.includes(ownCharacterId);

  if (!alreadyDiscovered && ownCharacterId !== undefined) {
    discoveredBy.push(ownCharacterId);
    db.prepare("UPDATE play_campaign_settlements SET discovered_by = ? WHERE campaign_id = ? AND settlement_id = ?").run(
      JSON.stringify(discoveredBy),
      campaignId,
      settlementId,
    );
  }

  sendJson(
    res,
    alreadyDiscovered ? 200 : 201,
    settlementResponseShape(
      { ...settlement, discovered_by: JSON.stringify(discoveredBy) },
      actor,
      campaign.owner,
      ownCharacterId,
    ),
  );
}

export function handleGetPlaySettlements(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT settlement_id, sequence, name, services, availability, discovered_by FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlaySettlementRow[];

  const isOwner = actor.username === campaign.owner;
  const ownCharacterId = isOwner ? undefined : getPlayCampaignMemberCharacter(campaignId, actor.username)?.character_id;

  const visibleRows = isOwner
    ? rows
    : rows.filter((row) => ownCharacterId !== undefined && (JSON.parse(row.discovered_by) as string[]).includes(ownCharacterId));

  sendJson(res, 200, {
    settlements: visibleRows.map((row) => settlementResponseShape(row, actor, campaign.owner, ownCharacterId)),
  });
}

// --- Settlement shops --------------------------------------------------------

interface PlayShopRow {
  shop_id: string;
  name: string;
  stock: string;
  buy_price: number;
  sell_price: number;
}

function getPlayShop(campaignId: string, settlementId: string, shopId: string): PlayShopRow | undefined {
  return db
    .prepare(
      "SELECT shop_id, name, stock, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
    )
    .get(campaignId, settlementId, shopId) as PlayShopRow | undefined;
}

function shopResponseShape(row: PlayShopRow): Record<string, unknown> {
  return {
    shop_id: row.shop_id,
    name: row.name,
    stock: JSON.parse(row.stock) as Record<string, number>,
    buy_price: row.buy_price,
    sell_price: row.sell_price,
  };
}

function parseShopStock(body: Record<string, unknown>): Record<string, number> | undefined {
  if (!isPlainObject(body.stock)) return undefined;
  const entries = Object.entries(body.stock);
  if (entries.length === 0) return undefined;
  const normalized: Record<string, number> = {};
  for (const [itemId, quantity] of entries) {
    if (!VALID_INVENTORY_ITEM_IDS.has(itemId) || !isValidInt(quantity, 1, Number.MAX_SAFE_INTEGER)) {
      return undefined;
    }
    normalized[itemId] = quantity as number;
  }
  return normalized;
}

export function handleCreatePlayShop(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    sendJson(res, 404, { error: "settlement not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.shop_id !== "string" ||
    body.shop_id.length === 0 ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    !isValidInt(body.buy_price, 1, Number.MAX_SAFE_INTEGER) ||
    !isValidInt(body.sell_price, 0, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const stock = parseShopStock(body);
  if (!stock) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayShop(campaignId, settlementId, body.shop_id)) {
    sendJson(res, 409, { error: "shop already exists" });
    return;
  }

  db.prepare(
    `INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(campaignId, settlementId, body.shop_id, body.name, JSON.stringify(stock), body.buy_price, body.sell_price);

  sendJson(
    res,
    201,
    shopResponseShape({
      shop_id: body.shop_id,
      name: body.name,
      stock: JSON.stringify(stock),
      buy_price: body.buy_price,
      sell_price: body.sell_price,
    }),
  );
}

export function handleGetPlayShop(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  shopId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    sendJson(res, 404, { error: "settlement not found" });
    return;
  }

  if (actor.username !== campaign.owner) {
    const member = getPlayCampaignMemberCharacter(campaignId, actor.username);
    const ownCharacterId = member?.character_id;
    const discoveredBy = JSON.parse(settlement.discovered_by) as string[];
    if (ownCharacterId === undefined || !discoveredBy.includes(ownCharacterId)) {
      sendJson(res, 404, { error: "shop not found" });
      return;
    }
  }

  const shop = getPlayShop(campaignId, settlementId, shopId);
  if (!shop) {
    sendJson(res, 404, { error: "shop not found" });
    return;
  }

  sendJson(res, 200, shopResponseShape(shop));
}

function parseShopTransactionBody(body: unknown): { characterId: string; itemId: string; quantity: number } | undefined {
  if (
    !isPlainObject(body) ||
    typeof body.character_id !== "string" ||
    body.character_id.length === 0 ||
    typeof body.item_id !== "string" ||
    !VALID_INVENTORY_ITEM_IDS.has(body.item_id) ||
    !isValidInt(body.quantity, 1, Number.MAX_SAFE_INTEGER)
  ) {
    return undefined;
  }
  return { characterId: body.character_id, itemId: body.item_id, quantity: body.quantity as number };
}

export function handleBuyFromPlayShop(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  shopId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    sendJson(res, 404, { error: "settlement not found" });
    return;
  }

  const shop = getPlayShop(campaignId, settlementId, shopId);
  if (!shop) {
    sendJson(res, 404, { error: "shop not found" });
    return;
  }

  const parsed = parseShopTransactionBody(body);
  if (!parsed) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }
  const { characterId, itemId, quantity } = parsed;

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const stock = JSON.parse(shop.stock) as Record<string, number>;
  const currentStock = stock[itemId] ?? 0;
  const totalCost = shop.buy_price * quantity;
  const gold = getPlayCampaignCharacterGold(campaignId, characterId);

  if (currentStock < quantity || gold === undefined || gold < totalCost) {
    sendJson(res, 409, { error: "insufficient stock or funds" });
    return;
  }

  const newStock = currentStock - quantity;
  stock[itemId] = newStock;
  const newGold = gold - totalCost;
  const currentQuantity = getPlayCampaignInventoryQuantity(campaignId, characterId, itemId);
  const newQuantity = currentQuantity + quantity;

  db.prepare(
    "UPDATE play_campaign_shops SET stock = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
  ).run(JSON.stringify(stock), campaignId, settlementId, shopId);
  db.prepare("UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?").run(
    newGold,
    campaignId,
    characterId,
  );
  db.prepare(
    `INSERT INTO play_campaign_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity`,
  ).run(campaignId, characterId, itemId, newQuantity);

  sendJson(res, 200, {
    character_id: characterId,
    item_id: itemId,
    quantity,
    gold: newGold,
    stock: newStock,
  });
}

export function handleSellToPlayShop(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  shopId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    sendJson(res, 404, { error: "settlement not found" });
    return;
  }

  const shop = getPlayShop(campaignId, settlementId, shopId);
  if (!shop) {
    sendJson(res, 404, { error: "shop not found" });
    return;
  }

  const parsed = parseShopTransactionBody(body);
  if (!parsed) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }
  const { characterId, itemId, quantity } = parsed;

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const currentQuantity = getPlayCampaignInventoryQuantity(campaignId, characterId, itemId);
  if (currentQuantity < quantity) {
    sendJson(res, 409, { error: "insufficient inventory" });
    return;
  }

  const stock = JSON.parse(shop.stock) as Record<string, number>;
  const currentStock = stock[itemId] ?? 0;
  const newStock = currentStock + quantity;
  stock[itemId] = newStock;

  const gold = getPlayCampaignCharacterGold(campaignId, characterId) ?? 0;
  const newGold = gold + shop.sell_price * quantity;
  const newQuantity = currentQuantity - quantity;

  if (newQuantity === 0) {
    db.prepare("DELETE FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?").run(
      campaignId,
      characterId,
      itemId,
    );
  } else {
    db.prepare(
      "UPDATE play_campaign_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
    ).run(newQuantity, campaignId, characterId, itemId);
  }
  db.prepare(
    "UPDATE play_campaign_shops SET stock = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
  ).run(JSON.stringify(stock), campaignId, settlementId, shopId);
  db.prepare("UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?").run(
    newGold,
    campaignId,
    characterId,
  );

  sendJson(res, 200, {
    character_id: characterId,
    item_id: itemId,
    quantity,
    gold: newGold,
    stock: newStock,
  });
}

// --- Crafting recipes --------------------------------------------------------

interface PlayRecipeRow {
  recipe_id: string;
  name: string;
  ingredients: string;
  output_item: string;
  output_quantity: number;
}

function getPlayRecipe(campaignId: string, recipeId: string): PlayRecipeRow | undefined {
  return db
    .prepare(
      "SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
    )
    .get(campaignId, recipeId) as PlayRecipeRow | undefined;
}

function recipeResponseShape(row: PlayRecipeRow): Record<string, unknown> {
  return {
    recipe_id: row.recipe_id,
    name: row.name,
    ingredients: JSON.parse(row.ingredients) as Record<string, number>,
    output_item: row.output_item,
    output_quantity: row.output_quantity,
  };
}

function nextPlayRecipeSequence(campaignId: string): number {
  const row = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) AS max_sequence FROM play_campaign_recipes WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function parseRecipeIngredients(body: Record<string, unknown>): Record<string, number> | undefined {
  if (!isPlainObject(body.ingredients)) return undefined;
  const entries = Object.entries(body.ingredients);
  if (entries.length === 0) return undefined;
  const normalized: Record<string, number> = {};
  for (const [itemId, quantity] of entries) {
    if (!VALID_INVENTORY_ITEM_IDS.has(itemId) || !isValidInt(quantity, 1, Number.MAX_SAFE_INTEGER)) {
      return undefined;
    }
    normalized[itemId] = quantity as number;
  }
  return normalized;
}

export function handleCreatePlayRecipe(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.recipe_id !== "string" ||
    body.recipe_id.length === 0 ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    typeof body.output_item !== "string" ||
    !VALID_INVENTORY_ITEM_IDS.has(body.output_item) ||
    !isValidInt(body.output_quantity, 1, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const ingredients = parseRecipeIngredients(body);
  if (!ingredients) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayRecipe(campaignId, body.recipe_id)) {
    sendJson(res, 409, { error: "recipe already exists" });
    return;
  }

  const sequence = nextPlayRecipeSequence(campaignId);
  db.prepare(
    `INSERT INTO play_campaign_recipes (campaign_id, recipe_id, sequence, name, ingredients, output_item, output_quantity)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    campaignId,
    body.recipe_id,
    sequence,
    body.name,
    JSON.stringify(ingredients),
    body.output_item,
    body.output_quantity,
  );

  sendJson(
    res,
    201,
    recipeResponseShape({
      recipe_id: body.recipe_id,
      name: body.name,
      ingredients: JSON.stringify(ingredients),
      output_item: body.output_item,
      output_quantity: body.output_quantity,
    }),
  );
}

export function handleGetPlayRecipes(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayRecipeRow[];

  sendJson(res, 200, { recipes: rows.map(recipeResponseShape) });
}

export function handleCraftPlayRecipe(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  recipeId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const recipe = getPlayRecipe(campaignId, recipeId);
  if (!recipe) {
    sendJson(res, 404, { error: "recipe not found" });
    return;
  }

  if (!isPlainObject(body) || typeof body.character_id !== "string" || body.character_id.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, body.character_id);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const ingredients = JSON.parse(recipe.ingredients) as Record<string, number>;
  for (const [itemId, quantity] of Object.entries(ingredients)) {
    if (getPlayCampaignInventoryQuantity(campaignId, body.character_id, itemId) < quantity) {
      sendJson(res, 409, { error: "insufficient ingredients" });
      return;
    }
  }

  for (const [itemId, quantity] of Object.entries(ingredients)) {
    const currentQuantity = getPlayCampaignInventoryQuantity(campaignId, body.character_id, itemId);
    const remainingQuantity = currentQuantity - quantity;
    if (remainingQuantity === 0) {
      db.prepare(
        "DELETE FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
      ).run(campaignId, body.character_id, itemId);
    } else {
      db.prepare(
        "UPDATE play_campaign_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
      ).run(remainingQuantity, campaignId, body.character_id, itemId);
    }
  }

  const currentOutputQuantity = getPlayCampaignInventoryQuantity(campaignId, body.character_id, recipe.output_item);
  const newOutputQuantity = currentOutputQuantity + recipe.output_quantity;
  db.prepare(
    `INSERT INTO play_campaign_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity`,
  ).run(campaignId, body.character_id, recipe.output_item, newOutputQuantity);

  sendJson(res, 201, {
    character_id: body.character_id,
    recipe_id: recipe.recipe_id,
    output_item: recipe.output_item,
    output_quantity: recipe.output_quantity,
  });
}

// --- Recurring downtime activities -----------------------------------------

interface PlayDowntimeActivityRow {
  activity_id: string;
  name: string;
  cycles_required: number;
}

function getPlayDowntimeActivity(campaignId: string, activityId: string): PlayDowntimeActivityRow | undefined {
  return db
    .prepare(
      "SELECT activity_id, name, cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?",
    )
    .get(campaignId, activityId) as PlayDowntimeActivityRow | undefined;
}

function downtimeActivityResponseShape(row: PlayDowntimeActivityRow): Record<string, unknown> {
  return {
    activity_id: row.activity_id,
    name: row.name,
    cycles_required: row.cycles_required,
  };
}

function nextPlayDowntimeActivitySequence(campaignId: string): number {
  const row = db
    .prepare(
      "SELECT COALESCE(MAX(sequence), -1) AS max_sequence FROM play_campaign_downtime_activities WHERE campaign_id = ?",
    )
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

interface PlayDowntimeAllocationRow {
  character_id: string;
  activity_id: string;
  cycles_completed: number;
  completions: number;
}

function getPlayDowntimeAllocation(
  campaignId: string,
  characterId: string,
  activityId: string,
): PlayDowntimeAllocationRow | undefined {
  return db
    .prepare(
      "SELECT character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
    )
    .get(campaignId, characterId, activityId) as PlayDowntimeAllocationRow | undefined;
}

function downtimeAllocationResponseShape(row: PlayDowntimeAllocationRow): Record<string, unknown> {
  return {
    character_id: row.character_id,
    activity_id: row.activity_id,
    cycles_completed: row.cycles_completed,
    completions: row.completions,
  };
}

export function handleCreatePlayDowntimeActivity(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.activity_id !== "string" ||
    body.activity_id.length === 0 ||
    typeof body.name !== "string" ||
    body.name.length === 0 ||
    !isValidInt(body.cycles_required, 1, 10)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayDowntimeActivity(campaignId, body.activity_id)) {
    sendJson(res, 409, { error: "activity already exists" });
    return;
  }

  const sequence = nextPlayDowntimeActivitySequence(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, sequence, name, cycles_required) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, body.activity_id, sequence, body.name, body.cycles_required);

  sendJson(
    res,
    201,
    downtimeActivityResponseShape({
      activity_id: body.activity_id,
      name: body.name,
      cycles_required: body.cycles_required,
    }),
  );
}

export function handleCreatePlayDowntimeAllocation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!isPlainObject(body) || typeof body.activity_id !== "string" || body.activity_id.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const activity = getPlayDowntimeActivity(campaignId, body.activity_id);
  if (!activity) {
    sendJson(res, 404, { error: "activity not found" });
    return;
  }

  if (getPlayDowntimeAllocation(campaignId, characterId, body.activity_id)) {
    sendJson(res, 409, { error: "allocation already exists" });
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)",
  ).run(campaignId, characterId, body.activity_id);

  sendJson(
    res,
    201,
    downtimeAllocationResponseShape({
      character_id: characterId,
      activity_id: body.activity_id,
      cycles_completed: 0,
      completions: 0,
    }),
  );
}

export function handleProgressPlayDowntimeAllocation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  activityId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (character.owner === null || character.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const activity = getPlayDowntimeActivity(campaignId, activityId);
  if (!activity) {
    sendJson(res, 404, { error: "activity not found" });
    return;
  }

  const allocation = getPlayDowntimeAllocation(campaignId, characterId, activityId);
  if (!allocation) {
    sendJson(res, 404, { error: "allocation not found" });
    return;
  }

  let cyclesCompleted = allocation.cycles_completed + 1;
  let completions = allocation.completions;
  if (cyclesCompleted >= activity.cycles_required) {
    cyclesCompleted = 0;
    completions += 1;
  }

  db.prepare(
    "UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
  ).run(cyclesCompleted, completions, campaignId, characterId, activityId);

  sendJson(
    res,
    200,
    downtimeAllocationResponseShape({
      character_id: characterId,
      activity_id: activityId,
      cycles_completed: cyclesCompleted,
      completions,
    }),
  );
}

export function handleGetPlayDowntimeAllocation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  activityId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const character = getPlayCampaignCharacterOwner(campaignId, characterId);
  if (!character) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  const activity = getPlayDowntimeActivity(campaignId, activityId);
  if (!activity) {
    sendJson(res, 404, { error: "activity not found" });
    return;
  }

  const allocation = getPlayDowntimeAllocation(campaignId, characterId, activityId);
  if (!allocation) {
    sendJson(res, 404, { error: "allocation not found" });
    return;
  }

  sendJson(res, 200, downtimeAllocationResponseShape(allocation));
}

// --- Session-zero settings: pre-start rules/tone/consent boundaries --------

interface PlaySessionZeroRow {
  rules: string;
  tone: string;
  consent: string;
}

function getPlaySessionZero(campaignId: string): PlaySessionZeroRow | undefined {
  return db.prepare("SELECT rules, tone, consent FROM play_campaign_session_zero WHERE campaign_id = ?").get(
    campaignId,
  ) as PlaySessionZeroRow | undefined;
}

function sessionZeroResponseShape(row: PlaySessionZeroRow): { rules: string; tone: string; consent: string[] } {
  return { rules: row.rules, tone: row.tone, consent: JSON.parse(row.consent) };
}

function isValidSessionZeroBody(
  body: unknown,
): body is { rules: string; tone: string; consent: string[] } {
  if (!isPlainObject(body)) return false;
  if (typeof body.rules !== "string" || body.rules.length === 0) return false;
  if (typeof body.tone !== "string" || body.tone.length === 0) return false;
  if (!Array.isArray(body.consent) || body.consent.length === 0) return false;
  if (!body.consent.every((item): item is string => typeof item === "string" && item.length > 0)) return false;
  if (new Set(body.consent).size !== body.consent.length) return false;
  return true;
}

export function handlePutPlaySessionZero(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isValidSessionZeroBody(body)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (campaign.status !== "lobby") {
    sendJson(res, 409, { error: "campaign already started" });
    return;
  }

  const consent = JSON.stringify(body.consent);
  db.prepare(
    "INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent = excluded.consent",
  ).run(campaignId, body.rules, body.tone, consent);

  sendJson(res, 200, { rules: body.rules, tone: body.tone, consent: body.consent });
}

export function handleGetPlaySessionZero(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const row = getPlaySessionZero(campaignId);
  if (!row) {
    sendJson(res, 404, { error: "session-zero settings not found" });
    return;
  }

  sendJson(res, 200, sessionZeroResponseShape(row));
}

// --- Content tags: campaign content records with role-filtered tags --------

interface PlayContentRow {
  content_id: string;
  kind: string;
  text: string;
  tags: string;
  sequence: number;
}

interface PlayContent {
  content_id: string;
  kind: string;
  text: string;
  tags: string[];
}

function contentResponseShape(row: PlayContentRow): PlayContent {
  return { content_id: row.content_id, kind: row.kind, text: row.text, tags: JSON.parse(row.tags) };
}

function isUniqueNonEmptyStringArray(value: unknown): value is string[] {
  if (!Array.isArray(value)) return false;
  if (!value.every((item): item is string => typeof item === "string" && item.length > 0)) return false;
  return new Set(value).size === value.length;
}

function isValidPlayContentBody(
  body: unknown,
): body is { content_id: string; kind: string; text: string; tags: string[] } {
  if (!isPlainObject(body)) return false;
  if (typeof body.content_id !== "string" || body.content_id.length === 0) return false;
  if (typeof body.kind !== "string" || body.kind.length === 0) return false;
  if (typeof body.text !== "string" || body.text.length === 0) return false;
  if (!isUniqueNonEmptyStringArray(body.tags) || body.tags.length === 0) return false;
  return true;
}

export function handleCreatePlayContent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isValidPlayContentBody(body)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = db
    .prepare("SELECT 1 FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?")
    .get(campaignId, body.content_id);
  if (existing) {
    sendJson(res, 409, { error: "content already exists" });
    return;
  }

  const { sequence } = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) + 1 AS sequence FROM play_campaign_content WHERE campaign_id = ?")
    .get(campaignId) as { sequence: number };

  db.prepare(
    "INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags, sequence) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, body.content_id, body.kind, body.text, JSON.stringify(body.tags), sequence);

  sendJson(res, 201, { content_id: body.content_id, kind: body.kind, text: body.text, tags: body.tags });
}

export function handlePutPlayContentTags(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  contentId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const row = db
    .prepare("SELECT content_id, kind, text, tags, sequence FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?")
    .get(campaignId, contentId) as PlayContentRow | undefined;
  if (!row) {
    sendJson(res, 404, { error: "content not found" });
    return;
  }

  if (!isPlainObject(body) || !isUniqueNonEmptyStringArray(body.tags)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  db.prepare("UPDATE play_campaign_content SET tags = ? WHERE campaign_id = ? AND content_id = ?").run(
    JSON.stringify(body.tags),
    campaignId,
    contentId,
  );

  sendJson(res, 200, { content_id: row.content_id, kind: row.kind, text: row.text, tags: body.tags });
}

export function handleListPlayContent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  excludeTagParam: string | null,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (excludeTagParam !== null && excludeTagParam.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const rows = db
    .prepare(
      "SELECT content_id, kind, text, tags, sequence FROM play_campaign_content WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayContentRow[];

  const isDm = actor.username === campaign.owner;
  const items = rows
    .map(contentResponseShape)
    .filter((item) => isDm || excludeTagParam === null || !item.tags.includes(excludeTagParam));

  sendJson(res, 200, { content: items });
}

// --- Privacy controls: campaign notes ---------------------------------------

interface PlayNoteRow {
  note_id: string;
  text: string;
  visibility: string;
  owner: string;
  sequence: number;
}

interface PlayNote {
  note_id: string;
  text: string;
  visibility: string;
  owner: string;
}

function noteResponseShape(row: PlayNoteRow): PlayNote {
  return { note_id: row.note_id, text: row.text, visibility: row.visibility, owner: row.owner };
}

function isValidPlayNoteVisibility(value: unknown): value is "private" | "party" {
  return value === "private" || value === "party";
}

function isValidPlayNoteCreateBody(body: unknown): body is { note_id: string; text: string; visibility: string } {
  if (!isPlainObject(body)) return false;
  if (typeof body.note_id !== "string" || body.note_id.length === 0) return false;
  if (typeof body.text !== "string" || body.text.length === 0) return false;
  if (!isValidPlayNoteVisibility(body.visibility)) return false;
  return true;
}

function isValidPlayNoteUpdateBody(body: unknown): body is { text: string; visibility: string } {
  if (!isPlainObject(body)) return false;
  if (typeof body.text !== "string" || body.text.length === 0) return false;
  if (!isValidPlayNoteVisibility(body.visibility)) return false;
  return true;
}

function getPlayNote(campaignId: string, noteId: string): PlayNoteRow | undefined {
  return db
    .prepare(
      "SELECT note_id, text, visibility, owner, sequence FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?",
    )
    .get(campaignId, noteId) as PlayNoteRow | undefined;
}

export function handleCreatePlayNote(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (!isValidPlayNoteCreateBody(body)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayNote(campaignId, body.note_id)) {
    sendJson(res, 409, { error: "note already exists" });
    return;
  }

  const { sequence } = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) + 1 AS sequence FROM play_campaign_notes WHERE campaign_id = ?")
    .get(campaignId) as { sequence: number };

  db.prepare(
    "INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner, sequence) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, body.note_id, body.text, body.visibility, actor.username, sequence);

  sendJson(res, 201, {
    note_id: body.note_id,
    text: body.text,
    visibility: body.visibility,
    owner: actor.username,
  });
}

export function handleListPlayNotes(res: ServerResponse, authHeader: string | undefined, campaignId: string): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT note_id, text, visibility, owner, sequence FROM play_campaign_notes WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayNoteRow[];

  const isDm = actor.username === campaign.owner;
  const notes = rows
    .filter((row) => isDm || row.visibility === "party" || row.owner === actor.username)
    .map(noteResponseShape);

  sendJson(res, 200, { notes });
}

export function handleGetPlayNote(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  noteId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const row = getPlayNote(campaignId, noteId);
  if (!row) {
    sendJson(res, 404, { error: "note not found" });
    return;
  }

  const isDm = actor.username === campaign.owner;
  if (!isDm && row.visibility === "private" && row.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  sendJson(res, 200, noteResponseShape(row));
}

export function handleUpdatePlayNote(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  noteId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const row = getPlayNote(campaignId, noteId);
  if (!row) {
    sendJson(res, 404, { error: "note not found" });
    return;
  }

  if (row.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!isValidPlayNoteUpdateBody(body)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  db.prepare("UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?").run(
    body.text,
    body.visibility,
    campaignId,
    noteId,
  );

  sendJson(res, 200, { note_id: row.note_id, text: body.text, visibility: body.visibility, owner: row.owner });
}

// --- Privacy controls: character-to-character whispers ----------------------

interface PlayWhisperRow {
  whisper_id: string;
  from_character_id: string;
  to_character_id: string;
  text: string;
  sequence: number;
}

interface PlayWhisper {
  whisper_id: string;
  from_character_id: string;
  to_character_id: string;
  text: string;
}

function whisperResponseShape(row: PlayWhisperRow): PlayWhisper {
  return {
    whisper_id: row.whisper_id,
    from_character_id: row.from_character_id,
    to_character_id: row.to_character_id,
    text: row.text,
  };
}

function isValidPlayWhisperBody(body: unknown): body is { whisper_id: string; to_character_id: string; text: string } {
  if (!isPlainObject(body)) return false;
  if (typeof body.whisper_id !== "string" || body.whisper_id.length === 0) return false;
  if (typeof body.to_character_id !== "string" || body.to_character_id.length === 0) return false;
  if (typeof body.text !== "string" || body.text.length === 0) return false;
  return true;
}

function getPlayWhisper(campaignId: string, whisperId: string): PlayWhisperRow | undefined {
  return db
    .prepare(
      "SELECT whisper_id, from_character_id, to_character_id, text, sequence FROM play_campaign_whispers WHERE campaign_id = ? AND whisper_id = ?",
    )
    .get(campaignId, whisperId) as PlayWhisperRow | undefined;
}

export function handleCreatePlayWhisper(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const sender = getPlayCampaignMemberCharacter(campaignId, actor.username);
  if (!sender) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!isValidPlayWhisperBody(body)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayWhisper(campaignId, body.whisper_id)) {
    sendJson(res, 409, { error: "whisper already exists" });
    return;
  }

  if (!hasPlayCampaignCharacter(campaignId, body.to_character_id)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const { sequence } = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) + 1 AS sequence FROM play_campaign_whispers WHERE campaign_id = ?")
    .get(campaignId) as { sequence: number };

  db.prepare(
    "INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text, sequence) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, body.whisper_id, sender.character_id, body.to_character_id, body.text, sequence);

  sendJson(res, 201, {
    whisper_id: body.whisper_id,
    from_character_id: sender.character_id,
    to_character_id: body.to_character_id,
    text: body.text,
  });
}

export function handleListPlayWhispers(res: ServerResponse, authHeader: string | undefined, campaignId: string): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT whisper_id, from_character_id, to_character_id, text, sequence FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayWhisperRow[];

  const isDm = actor.username === campaign.owner;
  const ownCharacter = isDm ? undefined : getPlayCampaignMemberCharacter(campaignId, actor.username);
  const whispers = rows
    .filter(
      (row) =>
        isDm ||
        (ownCharacter !== undefined &&
          (row.from_character_id === ownCharacter.character_id || row.to_character_id === ownCharacter.character_id)),
    )
    .map(whisperResponseShape);

  sendJson(res, 200, { whispers });
}

// --- Privacy controls: basic character sheets -------------------------------

interface PlayCharacterSheetRow {
  character_id: string;
  owner: string | null;
  name: string;
  class: string;
  level: number;
  proficiency_bonus: number;
  hp_max: number;
  dex_modifier: number;
}

function getPlayCharacterSheetRow(campaignId: string, characterId: string): PlayCharacterSheetRow | undefined {
  return db
    .prepare(
      "SELECT character_id, owner, name, class, level, proficiency_bonus, hp_max, dex_modifier FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
    )
    .get(campaignId, characterId) as PlayCharacterSheetRow | undefined;
}

export function handleGetPlayCharacterSheet(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const row = getPlayCharacterSheetRow(campaignId, characterId);
  if (!row) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  const isDm = actor.username === campaign.owner;
  if (!isDm && row.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  sendJson(res, 200, {
    character_id: row.character_id,
    owner: row.owner,
    name: row.name,
    class: row.class,
    level: 1,
    proficiency_bonus: 2,
    hp_max: 10,
    armor_class: 10,
  });
}

// --- Campaign invitations ----------------------------------------------------

interface PlayInvitationRow {
  invitation_id: string;
  username: string;
  character_id: string;
  status: string;
  sequence: number;
}

interface PlayInvitation {
  invitation_id: string;
  username: string;
  character_id: string;
  status: string;
}

function invitationResponseShape(row: PlayInvitationRow): PlayInvitation {
  return {
    invitation_id: row.invitation_id,
    username: row.username,
    character_id: row.character_id,
    status: row.status,
  };
}

function isValidPlayInvitationCreateBody(
  body: unknown,
): body is { invitation_id: string; username: string; character_id: string } {
  if (!isPlainObject(body)) return false;
  if (typeof body.invitation_id !== "string" || body.invitation_id.length === 0) return false;
  if (typeof body.username !== "string" || body.username.length === 0) return false;
  if (typeof body.character_id !== "string" || body.character_id.length === 0) return false;
  return true;
}

function getRegisteredUserRole(username: string): string | undefined {
  const row = db.prepare("SELECT role FROM users WHERE username = ?").get(username) as
    | { role: string }
    | undefined;
  return row?.role;
}

function getPlayInvitation(campaignId: string, invitationId: string): PlayInvitationRow | undefined {
  return db
    .prepare(
      "SELECT invitation_id, username, character_id, status, sequence FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?",
    )
    .get(campaignId, invitationId) as PlayInvitationRow | undefined;
}

function hasActivePlayInvitationForUsername(campaignId: string, username: string): boolean {
  const row = db
    .prepare(
      "SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? AND status = 'pending'",
    )
    .get(campaignId, username);
  return row !== undefined;
}

export function handleCreatePlayInvitation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isValidPlayInvitationCreateBody(body)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getRegisteredUserRole(body.username) !== "player") {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlayInvitation(campaignId, body.invitation_id)) {
    sendJson(res, 409, { error: "invitation already exists" });
    return;
  }

  if (hasActivePlayInvitationForUsername(campaignId, body.username)) {
    sendJson(res, 409, { error: "duplicate active invitation" });
    return;
  }

  const { sequence } = db
    .prepare("SELECT COALESCE(MAX(sequence), -1) + 1 AS sequence FROM play_campaign_invitations WHERE campaign_id = ?")
    .get(campaignId) as { sequence: number };

  db.prepare(
    "INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status, sequence) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, body.invitation_id, body.username, body.character_id, "pending", sequence);

  sendJson(res, 201, {
    invitation_id: body.invitation_id,
    username: body.username,
    character_id: body.character_id,
    status: "pending",
  });
}

export function handleListPlayInvitations(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isDm = actor.username === campaign.owner;
  const rows = db
    .prepare(
      "SELECT invitation_id, username, character_id, status, sequence FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayInvitationRow[];

  const invitations = rows
    .filter((row) => isDm || row.username === actor.username)
    .map(invitationResponseShape);

  if (!isDm && !hasPlayCampaignMember(campaignId, actor.username) && invitations.length === 0) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  sendJson(res, 200, { invitations });
}

export function handleAcceptPlayInvitation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  invitationId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const invitation = getPlayInvitation(campaignId, invitationId);
  if (!invitation) {
    sendJson(res, 404, { error: "invitation not found" });
    return;
  }

  if (actor.username !== invitation.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (invitation.status !== "pending") {
    sendJson(res, 409, { error: "invitation already accepted" });
    return;
  }

  if (
    hasPlayCampaignMember(campaignId, actor.username) ||
    hasPlayCampaignCharacter(campaignId, invitation.character_id) ||
    countPlayCampaignMembers(campaignId) >= campaign.max_players
  ) {
    sendJson(res, 409, { error: "cannot accept invitation" });
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, actor.username, invitation.character_id, actor.username, "adventurer", actor.username);

  db.prepare("UPDATE play_campaign_invitations SET status = ? WHERE campaign_id = ? AND invitation_id = ?").run(
    "accepted",
    campaignId,
    invitationId,
  );

  sendJson(res, 200, {
    invitation_id: invitation.invitation_id,
    username: invitation.username,
    character_id: invitation.character_id,
    status: "accepted",
  });
}

// --- GM delegation: campaign-scoped co-GM authority ------------------------

const VALID_DELEGATION_POWERS = new Set(["narrate"]);

interface PlayDelegationRow {
  username: string;
  powers: string;
  active: number;
}

interface PlayDelegation {
  username: string;
  powers: string[];
  active: boolean;
}

function delegationResponseShape(row: PlayDelegationRow): PlayDelegation {
  return {
    username: row.username,
    powers: JSON.parse(row.powers) as string[],
    active: row.active === 1,
  };
}

function getPlayDelegation(campaignId: string, username: string): PlayDelegationRow | undefined {
  return db
    .prepare("SELECT username, powers, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?")
    .get(campaignId, username) as PlayDelegationRow | undefined;
}

function hasActivePlayDelegation(campaignId: string, username: string, power: string): boolean {
  const row = getPlayDelegation(campaignId, username);
  if (!row || row.active !== 1) return false;
  const powers = JSON.parse(row.powers) as string[];
  return powers.includes(power);
}

function isValidPlayDelegationPowers(powers: unknown): powers is string[] {
  if (!Array.isArray(powers) || powers.length === 0) return false;
  const seen = new Set<string>();
  for (const power of powers) {
    if (typeof power !== "string" || !VALID_DELEGATION_POWERS.has(power) || seen.has(power)) return false;
    seen.add(power);
  }
  return true;
}

function nextPlayCampaignDelegationAuditSequence(campaignId: string): number {
  const row = db
    .prepare("SELECT MAX(sequence) AS max_sequence FROM play_campaign_delegation_audit WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number | null };
  return (row.max_sequence ?? 0) + 1;
}

function insertPlayCampaignDelegationAuditEntry(
  campaignId: string,
  username: string,
  action: string,
  powers: string[],
): void {
  const sequence = nextPlayCampaignDelegationAuditSequence(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, sequence, username, action, JSON.stringify(powers));
}

export function handleGrantPlayDelegation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.username !== "string" ||
    body.username.length === 0 ||
    !isValidPlayDelegationPowers(body.powers)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!hasPlayCampaignMember(campaignId, body.username)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = getPlayDelegation(campaignId, body.username);
  if (existing && existing.active === 1) {
    sendJson(res, 409, { error: "duplicate active delegation" });
    return;
  }

  db.prepare(
    `INSERT INTO play_campaign_delegations (campaign_id, username, powers, active) VALUES (?, ?, ?, 1)
     ON CONFLICT(campaign_id, username) DO UPDATE SET powers = excluded.powers, active = 1`,
  ).run(campaignId, body.username, JSON.stringify(body.powers));

  insertPlayCampaignDelegationAuditEntry(campaignId, body.username, "granted", body.powers);

  sendJson(res, 201, { username: body.username, powers: body.powers, active: true });
}

export function handleRevokePlayDelegation(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  username: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const existing = getPlayDelegation(campaignId, username);
  if (!existing || existing.active !== 1) {
    sendJson(res, 404, { error: "delegation not found" });
    return;
  }

  db.prepare("UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?").run(
    campaignId,
    username,
  );

  const powers = JSON.parse(existing.powers) as string[];
  insertPlayCampaignDelegationAuditEntry(campaignId, username, "revoked", powers);

  sendJson(res, 200, { username, powers, active: false });
}

export function handleGetPlayDelegationAudit(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT username, action, powers FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as { username: string; action: string; powers: string }[];

  const entries = rows.map((row) => ({
    username: row.username,
    action: row.action,
    powers: JSON.parse(row.powers) as string[],
  }));

  sendJson(res, 200, { entries });
}

// --- Actor audit trail: campaign-scoped, immutable audit events ------------

function nextPlayCampaignAuditSequence(campaignId: string): number {
  const row = db
    .prepare("SELECT MAX(sequence) AS max_sequence FROM play_campaign_audit_events WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number | null };
  return (row.max_sequence ?? 0) + 1;
}

function hasPlayCampaignAuditCorrelation(campaignId: string, correlationId: string): boolean {
  const row = db
    .prepare("SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?")
    .get(campaignId, correlationId);
  return row !== undefined;
}

export function handleCreatePlayAuditEvent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.kind !== "string" ||
    body.kind.length === 0 ||
    typeof body.correlation_id !== "string" ||
    body.correlation_id.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasPlayCampaignAuditCorrelation(campaignId, body.correlation_id)) {
    sendJson(res, 409, { error: "duplicate correlation_id" });
    return;
  }

  const role = isOwner ? "DM" : "player";
  const sequence = nextPlayCampaignAuditSequence(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_audit_events (campaign_id, sequence, kind, actor, role, correlation_id) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, sequence, body.kind, actor.username, role, body.correlation_id);

  sendJson(res, 201, {
    kind: body.kind,
    actor: actor.username,
    role,
    timestamp: sequence,
    correlation_id: body.correlation_id,
  });
}

export function handleGetPlayAuditEvents(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT kind, actor, role, sequence, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as { kind: string; actor: string; role: string; sequence: number; correlation_id: string }[];

  const entries = rows.map((row) => ({
    kind: row.kind,
    actor: row.actor,
    role: row.role,
    timestamp: row.sequence,
    correlation_id: row.correlation_id,
  }));

  sendJson(res, 200, { entries });
}

// --- Event projections: campaign-scoped, deterministic rebuild from an
// ordered, immutable event log. --------------------------------------------

function nextPlayCampaignProjectionSequence(campaignId: string): number {
  const row = db
    .prepare("SELECT MAX(sequence) AS max_sequence FROM play_campaign_projection_events WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number | null };
  return (row.max_sequence ?? 0) + 1;
}

function hasPlayCampaignProjectionEventId(campaignId: string, eventId: string): boolean {
  const row = db
    .prepare("SELECT 1 FROM play_campaign_projection_events WHERE campaign_id = ? AND event_id = ?")
    .get(campaignId, eventId);
  return row !== undefined;
}

interface PlayCampaignProjectionEventRow {
  sequence: number;
  event_id: string;
  kind: string;
  value: string | null;
}

function buildPlayCampaignProjection(campaignId: string): {
  story: string;
  danger: number;
  applied_event_ids: string[];
} {
  const rows = db
    .prepare(
      "SELECT sequence, event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayCampaignProjectionEventRow[];

  let story = "";
  let danger = 0;
  const appliedEventIds: string[] = [];
  for (const row of rows) {
    if (row.kind === "set-story") {
      story = row.value ?? "";
    } else if (row.kind === "increment-danger") {
      danger += 1;
    }
    appliedEventIds.push(row.event_id);
  }

  return { story, danger, applied_event_ids: appliedEventIds };
}

export function handleCreatePlayProjectionEvent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isOwner = actor.username === campaign.owner;
  const isMember = hasPlayCampaignMember(campaignId, actor.username);
  if (!isOwner && !isMember) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }
  if (isOwner) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!isPlainObject(body) || typeof body.event_id !== "string" || body.event_id.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (body.kind !== "set-story" && body.kind !== "increment-danger") {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (body.kind === "set-story") {
    if (typeof body.value !== "string" || body.value.length === 0) {
      sendJson(res, 400, { error: "invalid request" });
      return;
    }
  } else if (body.value !== undefined) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasPlayCampaignProjectionEventId(campaignId, body.event_id)) {
    sendJson(res, 409, { error: "duplicate event_id" });
    return;
  }

  const sequence = nextPlayCampaignProjectionSequence(campaignId);
  const value = body.kind === "set-story" ? (body.value as string) : null;
  db.prepare(
    "INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, sequence, body.event_id, body.kind, value);
  incrementPlayCampaignMetric(campaignId, "projection_events");

  buildPlayCampaignProjection(campaignId);

  const responseBody: Record<string, unknown> = { sequence, event_id: body.event_id, kind: body.kind };
  if (body.kind === "set-story") {
    responseBody.value = body.value;
  }
  sendJson(res, 201, responseBody);
}

export function handleGetPlayProjection(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const projection = buildPlayCampaignProjection(campaignId);
  sendJson(res, 200, projection);
}

// --- Idempotency keys: campaign-scoped idempotent event creation. A repeat
// request with the same Idempotency-Key and identical payload replays the
// original stored effect instead of appending a new event. --------------

interface PlayCampaignIdempotentEventRow {
  sequence: number;
  event_id: string;
  value: string;
  idempotency_key: string;
}

function formatIdempotentEvent(row: PlayCampaignIdempotentEventRow): Record<string, unknown> {
  return {
    event_id: row.event_id,
    value: row.value,
    sequence: row.sequence,
    idempotency_key: row.idempotency_key,
  };
}

function nextPlayCampaignIdempotentSequence(campaignId: string): number {
  const row = db
    .prepare("SELECT MAX(sequence) AS max_sequence FROM play_campaign_idempotent_events WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number | null };
  return (row.max_sequence ?? 0) + 1;
}

export function handleCreatePlayIdempotentEvent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  idempotencyKeyHeader: string | string[] | undefined,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const rawKey = Array.isArray(idempotencyKeyHeader) ? idempotencyKeyHeader[0] : idempotencyKeyHeader;
  const idempotencyKey = typeof rawKey === "string" ? rawKey.trim() : "";
  if (idempotencyKey.length === 0) {
    sendJson(res, 400, { error: "missing idempotency key" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.event_id !== "string" ||
    body.event_id.length === 0 ||
    typeof body.value !== "string" ||
    body.value.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }
  const eventId = body.event_id;
  const value = body.value;

  const existingByKey = db
    .prepare(
      "SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?",
    )
    .get(campaignId, idempotencyKey) as PlayCampaignIdempotentEventRow | undefined;

  if (existingByKey) {
    if (existingByKey.event_id === eventId && existingByKey.value === value) {
      sendJson(res, 200, formatIdempotentEvent(existingByKey));
      return;
    }
    sendJson(res, 409, { error: "idempotency key conflict" });
    return;
  }

  const existingByEventId = db
    .prepare(
      "SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?",
    )
    .get(campaignId, eventId) as PlayCampaignIdempotentEventRow | undefined;

  if (existingByEventId) {
    sendJson(res, 409, { error: "duplicate event_id" });
    return;
  }

  const sequence = nextPlayCampaignIdempotentSequence(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, sequence, eventId, value, idempotencyKey);

  sendJson(res, 201, { event_id: eventId, value, sequence, idempotency_key: idempotencyKey });
}

export function handleGetPlayIdempotentEvents(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayCampaignIdempotentEventRow[];

  sendJson(res, 200, { events: rows.map(formatIdempotentEvent) });
}

// --- Concurrent turn safety: campaign-scoped safe turn submission. Rejects
// stale (expected_turn mismatched) submissions without advancing state, and
// rejects duplicate submission_ids without a second advance. ---------------

interface PlayCampaignSafeTurnRow {
  sequence: number;
  submission_id: string;
  action: string;
  accepted_turn: number;
  next_turn: number;
}

function formatSafeTurn(row: PlayCampaignSafeTurnRow): Record<string, unknown> {
  return {
    submission_id: row.submission_id,
    action: row.action,
    accepted_turn: row.accepted_turn,
    next_turn: row.next_turn,
  };
}

function getPlayCampaignSafeTurnCurrent(campaignId: string): number {
  const row = db
    .prepare("SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?")
    .get(campaignId) as { current_turn: number } | undefined;
  if (row) return row.current_turn;
  db.prepare("INSERT INTO play_campaign_safe_turn_state (campaign_id, current_turn) VALUES (?, 1)").run(
    campaignId,
  );
  return 1;
}

function nextPlayCampaignSafeTurnSequence(campaignId: string): number {
  const row = db
    .prepare("SELECT MAX(sequence) AS max_sequence FROM play_campaign_safe_turns WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number | null };
  return (row.max_sequence ?? 0) + 1;
}

export function handleSubmitPlaySafeTurn(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.submission_id !== "string" ||
    body.submission_id.length === 0 ||
    typeof body.action !== "string" ||
    body.action.length === 0 ||
    !isValidInt(body.expected_turn, 1, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }
  const submissionId = body.submission_id;
  const action = body.action;
  const expectedTurn = body.expected_turn;

  const existing = db
    .prepare(
      "SELECT sequence, submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turns WHERE campaign_id = ? AND submission_id = ?",
    )
    .get(campaignId, submissionId) as PlayCampaignSafeTurnRow | undefined;
  if (existing) {
    sendJson(res, 409, { error: "duplicate submission_id" });
    return;
  }

  const currentTurn = getPlayCampaignSafeTurnCurrent(campaignId);
  if (expectedTurn !== currentTurn) {
    sendJson(res, 409, { current_turn: currentTurn });
    return;
  }

  const nextTurn = currentTurn + 1;
  const sequence = nextPlayCampaignSafeTurnSequence(campaignId);
  db.prepare(
    "INSERT INTO play_campaign_safe_turns (campaign_id, sequence, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, sequence, submissionId, action, currentTurn, nextTurn);
  db.prepare("UPDATE play_campaign_safe_turn_state SET current_turn = ? WHERE campaign_id = ?").run(
    nextTurn,
    campaignId,
  );

  sendJson(res, 201, {
    submission_id: submissionId,
    action,
    accepted_turn: currentTurn,
    next_turn: nextTurn,
  });
}

export function handleGetPlaySafeTurns(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const currentTurn = getPlayCampaignSafeTurnCurrent(campaignId);
  const rows = db
    .prepare(
      "SELECT sequence, submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turns WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayCampaignSafeTurnRow[];

  sendJson(res, 200, { current_turn: currentTurn, accepted: rows.map(formatSafeTurn) });
}

// --- Transaction recovery: campaign-scoped transactional currency transfer.
// A `simulate_failure` request validates and prepares the operation, then
// returns 500 without changing either balance or appending a transfer
// record. A real transfer commits the debit, credit, and record together. --

interface PlayCampaignTransactionalTransferRow {
  sequence: number;
  from_character_id: string;
  to_character_id: string;
  amount: number;
  from_gold: number;
  to_gold: number;
}

function formatTransactionalTransfer(row: PlayCampaignTransactionalTransferRow): Record<string, unknown> {
  return {
    from_character_id: row.from_character_id,
    to_character_id: row.to_character_id,
    amount: row.amount,
    from_gold: row.from_gold,
    to_gold: row.to_gold,
    sequence: row.sequence,
  };
}

function nextPlayCampaignTransactionalTransferSequence(campaignId: string): number {
  const row = db
    .prepare(
      "SELECT MAX(sequence) AS max_sequence FROM play_campaign_transactional_transfers WHERE campaign_id = ?",
    )
    .get(campaignId) as { max_sequence: number | null };
  return (row.max_sequence ?? 0) + 1;
}

export function handleCreatePlayTransactionalTransfer(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !hasPlayCampaignMember(campaignId, actor.username)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.from_character_id !== "string" ||
    body.from_character_id.length === 0 ||
    typeof body.to_character_id !== "string" ||
    body.to_character_id.length === 0 ||
    typeof body.amount !== "number" ||
    !Number.isInteger(body.amount) ||
    typeof body.simulate_failure !== "boolean"
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const fromCharacterId = body.from_character_id;
  const toCharacterId = body.to_character_id;
  const amount = body.amount;
  const simulateFailure = body.simulate_failure;

  const fromCharacter = getPlayCampaignCharacterOwner(campaignId, fromCharacterId);
  if (!fromCharacter) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (fromCharacter.owner === null || fromCharacter.owner !== actor.username) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (toCharacterId === fromCharacterId || !hasPlayCampaignCharacter(campaignId, toCharacterId)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (amount <= 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const fromGold = getPlayCampaignCharacterGold(campaignId, fromCharacterId);
  const toGold = getPlayCampaignCharacterGold(campaignId, toCharacterId);
  if (fromGold === undefined || toGold === undefined) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (fromGold < amount) {
    sendJson(res, 409, { error: "insufficient gold" });
    return;
  }

  const newFromGold = fromGold - amount;
  const newToGold = toGold + amount;

  if (simulateFailure) {
    sendJson(res, 500, { error: "simulated failure" });
    return;
  }

  db.exec("BEGIN");
  try {
    db.prepare("UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?").run(
      newFromGold,
      campaignId,
      fromCharacterId,
    );
    db.prepare("UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?").run(
      newToGold,
      campaignId,
      toCharacterId,
    );

    const sequence = nextPlayCampaignTransactionalTransferSequence(campaignId);
    db.prepare(
      "INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ).run(campaignId, sequence, fromCharacterId, toCharacterId, amount, newFromGold, newToGold);
    db.exec("COMMIT");

    sendJson(res, 201, {
      from_character_id: fromCharacterId,
      to_character_id: toCharacterId,
      amount,
      from_gold: newFromGold,
      to_gold: newToGold,
      sequence,
    });
  } catch (err) {
    db.exec("ROLLBACK");
    throw err;
  }
}

export function handleGetPlayTransactionalTransfers(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT sequence, from_character_id, to_character_id, amount, from_gold, to_gold FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayCampaignTransactionalTransferRow[];

  sendJson(res, 200, { transfers: rows.map(formatTransactionalTransfer) });
}

// --- Versioned export: DM-only immutable snapshots of a campaign's public
// story and status. Each snapshot's version is one greater than the
// campaign's previous export count and is never mutated after creation. --

interface PlayCampaignOwnerStoryStatusRow {
  owner: string;
  doc_story: string;
  status: string;
}

function getPlayCampaignOwnerStoryStatus(id: string): PlayCampaignOwnerStoryStatusRow | undefined {
  return db.prepare("SELECT owner, doc_story, status FROM play_campaigns WHERE id = ?").get(id) as
    | PlayCampaignOwnerStoryStatusRow
    | undefined;
}

interface PlayCampaignExportRow {
  version: number;
  story: string;
  status: string;
}

function formatPlayCampaignExport(row: PlayCampaignExportRow): Record<string, unknown> {
  return { version: row.version, story: row.story, status: row.status };
}

export function handleCreatePlayCampaignExport(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStoryStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const row = db
    .prepare("SELECT MAX(version) AS max_version FROM play_campaign_exports WHERE campaign_id = ?")
    .get(campaignId) as { max_version: number | null };
  const version = (row.max_version ?? 0) + 1;

  db.prepare(
    "INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)",
  ).run(campaignId, version, campaign.doc_story, campaign.status);

  sendJson(res, 201, { version, story: campaign.doc_story, status: campaign.status });
}

export function handleGetPlayCampaignExports(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStoryStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const rows = db
    .prepare("SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version ASC")
    .all(campaignId) as unknown as PlayCampaignExportRow[];

  sendJson(res, 200, { exports: rows.map(formatPlayCampaignExport) });
}

export function handleGetPlayCampaignExport(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  versionParam: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStoryStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!/^[0-9]+$/.test(versionParam)) {
    sendJson(res, 404, { error: "export not found" });
    return;
  }
  const version = Number(versionParam);

  const row = db
    .prepare("SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?")
    .get(campaignId, version) as PlayCampaignExportRow | undefined;
  if (!row) {
    sendJson(res, 404, { error: "export not found" });
    return;
  }

  sendJson(res, 200, formatPlayCampaignExport(row));
}

interface PlayCampaignImportRow {
  version: number;
  story: string;
  status: string;
}

function formatPlayCampaignImport(row: PlayCampaignImportRow): Record<string, unknown> {
  return { version: row.version, story: row.story, status: row.status };
}

export function handleCreatePlayCampaignImport(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStoryStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    body.version !== 1 ||
    typeof body.story !== "string" ||
    body.story.length === 0 ||
    typeof body.status !== "string" ||
    (body.status !== "lobby" && body.status !== "started")
  ) {
    sendJson(res, 400, { error: "invalid import" });
    return;
  }

  const version = 1;
  const story = body.story;
  const status = body.status;

  db.prepare("UPDATE play_campaigns SET doc_story = ?, status = ? WHERE id = ?").run(story, status, campaignId);
  db.prepare(
    "INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?) " +
      "ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status",
  ).run(campaignId, version, story, status);

  sendJson(res, 200, { version, story, status });
}

export function handleGetPlayCampaignImportState(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStoryStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const row = db
    .prepare("SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?")
    .get(campaignId) as PlayCampaignImportRow | undefined;
  if (!row) {
    sendJson(res, 404, { error: "import state not found" });
    return;
  }

  sendJson(res, 200, formatPlayCampaignImport(row));
}

interface PlayCampaignNameOwnerRow {
  name: string;
  owner: string;
}

function getPlayCampaignNameOwner(id: string): PlayCampaignNameOwnerRow | undefined {
  return db.prepare("SELECT name, owner FROM play_campaigns WHERE id = ?").get(id) as
    | PlayCampaignNameOwnerRow
    | undefined;
}

interface PlayCampaignMigrationRow {
  schema_version: number;
  story: string;
  campaign_name: string;
}

function formatPlayCampaignMigration(row: PlayCampaignMigrationRow): Record<string, unknown> {
  return { schema_version: row.schema_version, story: row.story, campaign_name: row.campaign_name };
}

export function handleCreatePlayCampaignMigration(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignNameOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    body.schema_version !== 1 ||
    typeof body.story !== "string" ||
    body.story.length === 0
  ) {
    sendJson(res, 400, { error: "invalid migration" });
    return;
  }

  const story = body.story;

  const existing = db
    .prepare("SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?")
    .get(campaignId) as PlayCampaignMigrationRow | undefined;
  if (existing && existing.story === story) {
    sendJson(res, 200, formatPlayCampaignMigration(existing));
    return;
  }

  const migrated: PlayCampaignMigrationRow = {
    schema_version: 2,
    story,
    campaign_name: campaign.name,
  };

  db.prepare(
    "INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?) " +
      "ON CONFLICT(campaign_id) DO UPDATE SET schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name",
  ).run(campaignId, migrated.schema_version, migrated.story, migrated.campaign_name);

  sendJson(res, 201, formatPlayCampaignMigration(migrated));
}

export function handleGetPlayCampaignMigrationState(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignNameOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const row = db
    .prepare("SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?")
    .get(campaignId) as PlayCampaignMigrationRow | undefined;
  if (!row) {
    sendJson(res, 404, { error: "migration state not found" });
    return;
  }

  sendJson(res, 200, formatPlayCampaignMigration(row));
}

interface PlaySearchRecordRow {
  record_id: string;
  sequence: number;
  text: string;
}

export function handleCreatePlaySearchRecord(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.record_id !== "string" ||
    body.record_id.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = db
    .prepare("SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND record_id = ?")
    .get(campaignId, body.record_id);
  if (existing) {
    sendJson(res, 400, { error: "record_id already exists" });
    return;
  }

  const existingText = db
    .prepare("SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND text = ?")
    .get(campaignId, body.text);
  if (existingText) {
    sendJson(res, 400, { error: "text already exists" });
    return;
  }

  const { sequence } = db
    .prepare(
      "SELECT COALESCE(MAX(sequence), -1) + 1 AS sequence FROM play_campaign_search_records WHERE campaign_id = ?",
    )
    .get(campaignId) as { sequence: number };

  db.prepare(
    "INSERT INTO play_campaign_search_records (campaign_id, record_id, sequence, text) VALUES (?, ?, ?, ?)",
  ).run(campaignId, body.record_id, sequence, body.text);

  sendJson(res, 201, { record_id: body.record_id, text: body.text });
}

const SEARCH_RECORDS_DEFAULT_LIMIT = 2;
const SEARCH_RECORDS_MAX_LIMIT = 3;

export function handleListPlaySearchRecords(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  url: URL,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const q = url.searchParams.get("q");

  const limitParam = url.searchParams.get("limit");
  let limit = SEARCH_RECORDS_DEFAULT_LIMIT;
  if (limitParam !== null) {
    if (!/^-?\d+$/.test(limitParam)) {
      sendJson(res, 400, { error: "invalid limit" });
      return;
    }
    limit = Number(limitParam);
    if (!isValidInt(limit, 1, SEARCH_RECORDS_MAX_LIMIT)) {
      sendJson(res, 400, { error: "invalid limit" });
      return;
    }
  }

  const cursorParam = url.searchParams.get("cursor");
  let cursor = 0;
  if (cursorParam !== null) {
    if (!/^-?\d+$/.test(cursorParam)) {
      sendJson(res, 400, { error: "invalid cursor" });
      return;
    }
    cursor = Number(cursorParam);
    if (!isValidInt(cursor, 0, Number.MAX_SAFE_INTEGER)) {
      sendJson(res, 400, { error: "invalid cursor" });
      return;
    }
  }

  const rows = db
    .prepare("SELECT record_id, sequence, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY sequence ASC")
    .all(campaignId) as unknown as PlaySearchRecordRow[];

  const filtered = q === null ? rows : rows.filter((row) => row.text.toLowerCase().includes(q.toLowerCase()));

  const page = filtered.slice(cursor, cursor + limit);
  const nextCursor = cursor + limit < filtered.length ? cursor + limit : null;

  sendJson(res, 200, {
    records: page.map((row) => ({ record_id: row.record_id, text: row.text })),
    next_cursor: nextCursor,
  });
}

interface PlayRateEventRow {
  event_id: string;
  actor: string;
}

const RATE_EVENT_LIMIT = 2;

function ensurePlayCampaignMetricsRow(campaignId: string): void {
  db.prepare("INSERT OR IGNORE INTO play_campaign_metrics (campaign_id) VALUES (?)").run(campaignId);
}

function incrementPlayCampaignMetric(
  campaignId: string,
  column: "accepted_rate_events" | "rejected_rate_events" | "projection_events",
): void {
  ensurePlayCampaignMetricsRow(campaignId);
  db.prepare(`UPDATE play_campaign_metrics SET ${column} = ${column} + 1 WHERE campaign_id = ?`).run(campaignId);
}

export function handleCreatePlayRateEvent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (!isPlainObject(body) || typeof body.event_id !== "string" || body.event_id.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = db
    .prepare("SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?")
    .get(campaignId, body.event_id);
  if (existing) {
    sendJson(res, 400, { error: "event_id already exists" });
    return;
  }

  const { count } = db
    .prepare("SELECT COUNT(*) AS count FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?")
    .get(campaignId, actor.username) as { count: number };

  const remaining = RATE_EVENT_LIMIT - count;
  if (remaining <= 0) {
    incrementPlayCampaignMetric(campaignId, "rejected_rate_events");
    sendJson(res, 429, { limit: RATE_EVENT_LIMIT, remaining: 0 });
    return;
  }

  const { sequence } = db
    .prepare(
      "SELECT COALESCE(MAX(sequence), -1) + 1 AS sequence FROM play_campaign_rate_events WHERE campaign_id = ?",
    )
    .get(campaignId) as { sequence: number };

  db.prepare(
    "INSERT INTO play_campaign_rate_events (campaign_id, event_id, sequence, actor) VALUES (?, ?, ?, ?)",
  ).run(campaignId, body.event_id, sequence, actor.username);
  incrementPlayCampaignMetric(campaignId, "accepted_rate_events");

  sendJson(res, 201, { event_id: body.event_id, actor: actor.username, remaining: remaining - 1 });
}

export function handleListPlayRateEvents(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare("SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY sequence ASC")
    .all(campaignId) as unknown as PlayRateEventRow[];

  const { count } = db
    .prepare("SELECT COUNT(*) AS count FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?")
    .get(campaignId, actor.username) as { count: number };

  const remaining = Math.max(0, RATE_EVENT_LIMIT - count);

  sendJson(res, 200, {
    events: rows.map((row) => ({ event_id: row.event_id, actor: row.actor })),
    remaining,
  });
}

interface PlayCampaignMetricsRow {
  accepted_rate_events: number;
  rejected_rate_events: number;
  projection_events: number;
}

export function handleGetPlayCampaignMetrics(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const row = db
    .prepare(
      "SELECT accepted_rate_events, rejected_rate_events, projection_events FROM play_campaign_metrics WHERE campaign_id = ?",
    )
    .get(campaignId) as PlayCampaignMetricsRow | undefined;

  sendJson(res, 200, {
    accepted_rate_events: row?.accepted_rate_events ?? 0,
    rejected_rate_events: row?.rejected_rate_events ?? 0,
    projection_events: row?.projection_events ?? 0,
    uptime_ticks: 1,
  });
}

export function handleSetPlayServiceMode(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (actor.role !== "dm") {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!isPlainObject(body) || typeof body.maintenance !== "boolean") {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  setMaintenanceMode(body.maintenance);
  sendJson(res, 200, { maintenance: isMaintenanceMode() });
}

// --- Campaign backup / restore ---------------------------------------------

interface PlayCampaignBackupSourceRow {
  owner: string;
  story: string;
  status: string;
}

function getPlayCampaignBackupSource(id: string): PlayCampaignBackupSourceRow | undefined {
  return db.prepare("SELECT owner, doc_story AS story, status FROM play_campaigns WHERE id = ?").get(id) as
    | PlayCampaignBackupSourceRow
    | undefined;
}

interface PlayCampaignBackupRow {
  backup_id: string;
  story: string;
  status: string;
}

export function handleCreatePlayBackup(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignBackupSource(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const countRow = db
    .prepare("SELECT COUNT(*) AS count FROM play_campaign_backups WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const sequence = countRow.count + 1;
  const backupId = `backup-${sequence}`;

  db.prepare(
    "INSERT INTO play_campaign_backups (campaign_id, backup_id, sequence, story, status) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, backupId, sequence, campaign.story, campaign.status);

  sendJson(res, 201, { backup_id: backupId, story: campaign.story, status: campaign.status });
}

export function handleListPlayBackups(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignBackupSource(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayCampaignBackupRow[];

  sendJson(res, 200, {
    backups: rows.map((row) => ({ backup_id: row.backup_id, story: row.story, status: row.status })),
  });
}

export function handleRestorePlayBackup(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  backupId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignBackupSource(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const backup = db
    .prepare("SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?")
    .get(campaignId, backupId) as PlayCampaignBackupRow | undefined;
  if (!backup) {
    sendJson(res, 404, { error: "backup not found" });
    return;
  }

  db.prepare("UPDATE play_campaigns SET doc_story = ?, status = ? WHERE id = ?").run(
    backup.story,
    backup.status,
    campaignId,
  );

  sendJson(res, 200, { backup_id: backup.backup_id, story: backup.story, status: backup.status });
}

// --- Deterministic replay ---------------------------------------------------

interface PlayCampaignReplayEventRow {
  event_id: string;
  kind: string;
  text: string;
  sequence: number;
}

function getPlayReplayEvents(campaignId: string): PlayCampaignReplayEventRow[] {
  return db
    .prepare(
      "SELECT event_id, kind, text, sequence FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayCampaignReplayEventRow[];
}

function buildPlayReplayState(campaignId: string): { story: string; event_ids: string[]; digest: string } {
  const events = getPlayReplayEvents(campaignId);
  const story = events.map((event) => event.text).join("");
  const eventIds = events.map((event) => event.event_id);
  const digest = `${eventIds.join(",")}|${story}`;
  return { story, event_ids: eventIds, digest };
}

export function handleCreatePlayReplayEvent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.event_id !== "string" ||
    body.event_id.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0 ||
    typeof body.kind !== "string"
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (body.kind !== "append") {
    sendJson(res, 400, { error: "invalid kind" });
    return;
  }

  const existing = db
    .prepare("SELECT 1 FROM play_campaign_replay_events WHERE campaign_id = ? AND event_id = ?")
    .get(campaignId, body.event_id);
  if (existing) {
    sendJson(res, 409, { error: "event_id already exists" });
    return;
  }

  const countRow = db
    .prepare("SELECT COUNT(*) AS count FROM play_campaign_replay_events WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const sequence = countRow.count + 1;

  db.prepare(
    "INSERT INTO play_campaign_replay_events (campaign_id, event_id, sequence, kind, text) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, body.event_id, sequence, body.kind, body.text);

  sendJson(res, 201, { event_id: body.event_id, kind: body.kind, text: body.text, sequence });
}

export function handleGetPlayReplay(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  sendJson(res, 200, buildPlayReplayState(campaignId));
}

// --- Deterministic RNG ledger ------------------------------------------------

interface PlayCampaignRngRollRow {
  roll_id: string;
  sides: number;
  result: number;
  sequence: number;
}

function getPlayRngSeed(campaignId: string): string | undefined {
  const row = db.prepare("SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?").get(campaignId) as
    | { seed: string }
    | undefined;
  return row?.seed;
}

function getPlayRngRolls(campaignId: string): PlayCampaignRngRollRow[] {
  return db
    .prepare(
      "SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayCampaignRngRollRow[];
}

// acc stays within [0, 2^32) after each step, so `acc * 31 + b` never exceeds
// ~6.9e10 — well inside Number's exact-integer range — before the next mod.
function computeRngRoll(seed: string, sequence: number, rollId: string, sides: number): number {
  const bytes = Buffer.from(`${seed}|${sequence}|${rollId}|${sides}`, "utf8");
  let acc = 0;
  for (const b of bytes) {
    acc = (acc * 31 + b) % 4294967296;
  }
  return (acc % sides) + 1;
}

export function handleSetPlayRngSeed(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isPlainObject(body) || typeof body.seed !== "string" || body.seed.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = getPlayRngSeed(campaignId);
  if (existing !== undefined) {
    sendJson(res, 409, { error: "seed already configured" });
    return;
  }

  db.prepare("INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)").run(campaignId, body.seed);

  sendJson(res, 200, { seed: body.seed, rolls: [] });
}

export function handleAppendPlayRngRoll(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const seed = getPlayRngSeed(campaignId);
  if (seed === undefined) {
    sendJson(res, 409, { error: "seed not configured" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.roll_id !== "string" ||
    body.roll_id.length === 0 ||
    !isValidInt(body.sides, 2, 100)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = db
    .prepare("SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?")
    .get(campaignId, body.roll_id);
  if (existing) {
    sendJson(res, 409, { error: "roll_id already exists" });
    return;
  }

  const countRow = db
    .prepare("SELECT COUNT(*) AS count FROM play_campaign_rng_rolls WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const sequence = countRow.count + 1;
  const result = computeRngRoll(seed, sequence, body.roll_id, body.sides);

  db.prepare(
    "INSERT INTO play_campaign_rng_rolls (campaign_id, roll_id, sequence, sides, result) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, body.roll_id, sequence, body.sides, result);

  sendJson(res, 201, { roll_id: body.roll_id, sides: body.sides, result, sequence });
}

export function handleGetPlayRngLedger(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const seed = getPlayRngSeed(campaignId);
  const rolls = getPlayRngRolls(campaignId);

  sendJson(res, 200, {
    seed: seed ?? null,
    rolls: rolls.map((row) => ({
      roll_id: row.roll_id,
      sides: row.sides,
      result: row.result,
      sequence: row.sequence,
    })),
  });
}

interface PlayCampaignModerationReportRow {
  report_id: string;
  target_id: string;
  reason: string;
  status: string;
  reporter: string;
  sequence: number;
  action: string | null;
  note: string | null;
  resolver: string | null;
}

function getModerationReport(campaignId: string, reportId: string): PlayCampaignModerationReportRow | undefined {
  return db
    .prepare(
      "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?",
    )
    .get(campaignId, reportId) as PlayCampaignModerationReportRow | undefined;
}

function serializeModerationReport(row: PlayCampaignModerationReportRow): Record<string, unknown> {
  const base: Record<string, unknown> = {
    report_id: row.report_id,
    target_id: row.target_id,
    reason: row.reason,
    status: row.status,
    reporter: row.reporter,
    sequence: row.sequence,
  };
  if (row.status === "resolved") {
    base.action = row.action;
    base.note = row.note;
    base.resolver = row.resolver;
  }
  return base;
}

export function handleCreatePlayModerationReport(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.report_id !== "string" ||
    body.report_id.length === 0 ||
    typeof body.target_id !== "string" ||
    body.target_id.length === 0 ||
    typeof body.reason !== "string" ||
    body.reason.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = getModerationReport(campaignId, body.report_id);
  if (existing) {
    sendJson(res, 409, { error: "report_id already exists" });
    return;
  }

  const countRow = db
    .prepare("SELECT COUNT(*) AS count FROM play_campaign_moderation_reports WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const sequence = countRow.count + 1;

  db.prepare(
    "INSERT INTO play_campaign_moderation_reports (campaign_id, report_id, target_id, reason, status, reporter, sequence, action, note, resolver) VALUES (?, ?, ?, ?, 'open', ?, ?, NULL, NULL, NULL)",
  ).run(campaignId, body.report_id, body.target_id, body.reason, actor.username, sequence);

  const row = getModerationReport(campaignId, body.report_id)!;
  sendJson(res, 201, serializeModerationReport(row));
}

export function handleGetPlayModerationReports(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayCampaignModerationReportRow[];

  sendJson(res, 200, { reports: rows.map(serializeModerationReport) });
}

export function handleResolvePlayModerationReport(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  reportId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  const row = getModerationReport(campaignId, reportId);
  if (!row) {
    sendJson(res, 404, { error: "report not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    (body.action !== "allow" && body.action !== "remove") ||
    typeof body.note !== "string" ||
    body.note.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (row.status === "resolved") {
    sendJson(res, 409, { error: "report already resolved" });
    return;
  }

  db.prepare(
    "UPDATE play_campaign_moderation_reports SET status = 'resolved', action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ?",
  ).run(body.action, body.note, actor.username, campaignId, reportId);

  const updated = getModerationReport(campaignId, reportId)!;
  sendJson(res, 200, serializeModerationReport(updated));
}

interface PlaySafetyBoundariesRow {
  blocked_tags: string;
}

function getSafetyBoundaryTags(campaignId: string): string[] {
  const row = db
    .prepare("SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?")
    .get(campaignId) as PlaySafetyBoundariesRow | undefined;
  if (!row) return [];
  return JSON.parse(row.blocked_tags) as string[];
}

function isNonemptyUniqueStringArray(value: unknown): value is string[] {
  if (!Array.isArray(value) || value.length === 0) return false;
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item !== "string" || item.trim().length === 0) return false;
    if (seen.has(item)) return false;
    seen.add(item);
  }
  return true;
}

export function handlePutPlaySafetyBoundaries(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isPlainObject(body) || !isNonemptyUniqueStringArray(body.blocked_tags)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const sortedTags = [...body.blocked_tags].sort();

  db.prepare(
    "INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags = excluded.blocked_tags",
  ).run(campaignId, JSON.stringify(sortedTags));

  sendJson(res, 200, { blocked_tags: sortedTags });
}

export function handleGetPlaySafetyBoundaries(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  sendJson(res, 200, { blocked_tags: getSafetyBoundaryTags(campaignId) });
}

interface PlaySafetyEventRow {
  event_id: string;
  kind: string;
  text: string;
  tags: string;
  sequence: number;
}

function getSafetyEvent(campaignId: string, eventId: string): PlaySafetyEventRow | undefined {
  return db
    .prepare(
      "SELECT event_id, kind, text, tags, sequence FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?",
    )
    .get(campaignId, eventId) as PlaySafetyEventRow | undefined;
}

function serializeSafetyEvent(row: PlaySafetyEventRow): Record<string, unknown> {
  return {
    event_id: row.event_id,
    kind: row.kind,
    text: row.text,
    tags: JSON.parse(row.tags) as string[],
    sequence: row.sequence,
  };
}

export function handleCreatePlaySafetyCheck(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.event_id !== "string" ||
    body.event_id.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0 ||
    (body.kind !== "narration" && body.kind !== "chat") ||
    !isNonemptyUniqueStringArray(body.tags)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = getSafetyEvent(campaignId, body.event_id);
  if (existing) {
    sendJson(res, 409, { error: "event_id already accepted" });
    return;
  }

  const blockedTags = new Set(getSafetyBoundaryTags(campaignId));
  if (body.tags.some((tag) => blockedTags.has(tag))) {
    sendJson(res, 409, { error: "tag blocked" });
    return;
  }

  const countRow = db
    .prepare("SELECT COUNT(*) AS count FROM play_campaign_safety_events WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const sequence = countRow.count + 1;

  db.prepare(
    "INSERT INTO play_campaign_safety_events (campaign_id, event_id, kind, text, tags, sequence) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(campaignId, body.event_id, body.kind, body.text, JSON.stringify(body.tags), sequence);

  sendJson(res, 201, {
    event_id: body.event_id,
    kind: body.kind,
    text: body.text,
    tags: body.tags,
    sequence,
  });
}

export function handleGetPlaySafetyEvents(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const rows = db
    .prepare(
      "SELECT event_id, kind, text, tags, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlaySafetyEventRow[];

  sendJson(res, 200, { events: rows.map(serializeSafetyEvent) });
}

const CANONICAL_FIXTURE_ID = "canonical-v1";

function canonicalFixtureState(): Record<string, unknown> {
  return {
    fixture_id: CANONICAL_FIXTURE_ID,
    status: "seeded",
    characters: [
      { character_id: "fixture-hero", name: "Ari", class: "fighter" },
      { character_id: "fixture-mage", name: "Bea", class: "wizard" },
    ],
    story: "The lantern is lit.",
    event_ids: ["fixture-event-1", "fixture-event-2"],
  };
}

interface PlayFixtureSeedRow {
  fixture_id: string;
  status: string;
}

function getFixtureSeed(campaignId: string): PlayFixtureSeedRow | undefined {
  return db
    .prepare("SELECT fixture_id, status FROM play_campaign_fixture_seeds WHERE campaign_id = ?")
    .get(campaignId) as PlayFixtureSeedRow | undefined;
}

export function handleCreatePlayFixtureSeed(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isPlainObject(body) || typeof body.fixture_id !== "string" || body.fixture_id !== CANONICAL_FIXTURE_ID) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = getFixtureSeed(campaignId);
  if (existing) {
    sendJson(res, 200, canonicalFixtureState());
    return;
  }

  db.prepare(
    "INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id, status) VALUES (?, ?, 'seeded')",
  ).run(campaignId, CANONICAL_FIXTURE_ID);

  sendJson(res, 201, canonicalFixtureState());
}

export function handleGetPlayFixtureState(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const existing = getFixtureSeed(campaignId);
  if (!existing) {
    sendJson(res, 404, { error: "fixture not seeded" });
    return;
  }

  sendJson(res, 200, canonicalFixtureState());
}

const DM_ONBOARDING_STEPS = ["configure-safety", "invite-players", "start-campaign"];
const PLAYER_ONBOARDING_STEPS = ["review-party", "take-turn", "submit-action"];

export function handleGetPlayOnboarding(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwner(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (actor.username === campaign.owner) {
    sendJson(res, 200, { role: "dm", next_steps: DM_ONBOARDING_STEPS, can_mutate: true });
    return;
  }

  sendJson(res, 200, { role: "player", next_steps: PLAYER_ONBOARDING_STEPS, can_mutate: true });
}

// --- Spectator view: read-only public projection ----------------------------

const SPECTATOR_TOKEN_RE = /^spectator-(.+)$/;
const SESSION_TOKEN_RE = /^session-(.+)$/;

interface PlaySpectatorTicketRow {
  spectator_id: string;
  campaign_id: string;
}

function getPlaySpectatorTicketBySpectatorId(spectatorId: string): PlaySpectatorTicketRow | undefined {
  return db
    .prepare("SELECT spectator_id, campaign_id FROM play_campaign_spectators WHERE spectator_id = ?")
    .get(spectatorId) as PlaySpectatorTicketRow | undefined;
}

export function handleCreatePlaySpectatorTicket(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwner(res, actor, campaign.owner)) return;

  if (!isPlainObject(body) || typeof body.spectator_id !== "string" || body.spectator_id.length === 0) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getPlaySpectatorTicketBySpectatorId(body.spectator_id)) {
    sendJson(res, 409, { error: "spectator already exists" });
    return;
  }

  const token = `spectator-${body.spectator_id}`;
  db.prepare(
    "INSERT INTO play_campaign_spectators (spectator_id, campaign_id, token) VALUES (?, ?, ?)",
  ).run(body.spectator_id, campaignId, token);

  sendJson(res, 201, { spectator_id: body.spectator_id, token });
}

interface PlaySpectatorProjectionRow {
  name: string;
  status: string;
  doc_story: string;
}

function getPlaySpectatorProjectionRow(campaignId: string): PlaySpectatorProjectionRow | undefined {
  return db.prepare("SELECT name, status, doc_story FROM play_campaigns WHERE id = ?").get(campaignId) as
    | PlaySpectatorProjectionRow
    | undefined;
}

export function handleGetPlaySpectatorView(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
): void {
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    sendJson(res, 401, { error: "unauthorized" });
    return;
  }
  const token = authHeader.slice("Bearer ".length);
  const spectatorMatch = SPECTATOR_TOKEN_RE.exec(token);
  const sessionMatch = SESSION_TOKEN_RE.exec(token);
  if (!spectatorMatch && !sessionMatch) {
    sendJson(res, 401, { error: "unauthorized" });
    return;
  }

  const campaign = getPlaySpectatorProjectionRow(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (sessionMatch) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  const ticket = getPlaySpectatorTicketBySpectatorId(spectatorMatch![1]);
  if (!ticket) {
    sendJson(res, 401, { error: "unauthorized" });
    return;
  }
  if (ticket.campaign_id !== campaignId) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  sendJson(res, 200, {
    campaign_id: campaignId,
    name: campaign.name,
    status: campaign.status,
    party_size: countPlayCampaignMembers(campaignId),
    story: campaign.doc_story,
  });
}

// --- Event feed: append-only, cursor-paginated -----------------------------

interface PlayFeedEventRow {
  event_id: string;
  sequence: number;
  text: string;
}

const FEED_EVENTS_DEFAULT_LIMIT = 2;
const FEED_EVENTS_MAX_LIMIT = 3;

export function handleCreatePlayFeedEvent(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  body: unknown,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  if (
    !isPlainObject(body) ||
    typeof body.event_id !== "string" ||
    body.event_id.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const existing = db
    .prepare("SELECT 1 FROM play_campaign_feed_events WHERE campaign_id = ? AND event_id = ?")
    .get(campaignId, body.event_id);
  if (existing) {
    sendJson(res, 409, { error: "event already exists" });
    return;
  }

  const { sequence } = db
    .prepare(
      "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_feed_events WHERE campaign_id = ?",
    )
    .get(campaignId) as { sequence: number };

  db.prepare(
    "INSERT INTO play_campaign_feed_events (campaign_id, event_id, sequence, text) VALUES (?, ?, ?, ?)",
  ).run(campaignId, body.event_id, sequence, body.text);

  sendJson(res, 201, { event_id: body.event_id, text: body.text, sequence });
}

export function handleGetPlayEventFeed(
  res: ServerResponse,
  authHeader: string | undefined,
  campaignId: string,
  url: URL,
): void {
  const actor = requireActor(res, authHeader);
  if (!actor) return;

  const campaign = getPlayCampaignOwnerStatus(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!requireCampaignOwnerOrMember(res, campaignId, actor, campaign.owner)) return;

  const limitParam = url.searchParams.get("limit");
  let limit = FEED_EVENTS_DEFAULT_LIMIT;
  if (limitParam !== null) {
    if (!/^-?\d+$/.test(limitParam)) {
      sendJson(res, 400, { error: "invalid limit" });
      return;
    }
    limit = Number(limitParam);
    if (!isValidInt(limit, 1, FEED_EVENTS_MAX_LIMIT)) {
      sendJson(res, 400, { error: "invalid limit" });
      return;
    }
  }

  const cursorParam = url.searchParams.get("cursor");
  let cursor = 0;
  if (cursorParam !== null) {
    if (!/^-?\d+$/.test(cursorParam)) {
      sendJson(res, 400, { error: "invalid cursor" });
      return;
    }
    cursor = Number(cursorParam);
    if (!isValidInt(cursor, 0, Number.MAX_SAFE_INTEGER)) {
      sendJson(res, 400, { error: "invalid cursor" });
      return;
    }
  }

  const rows = db
    .prepare(
      "SELECT event_id, sequence, text FROM play_campaign_feed_events WHERE campaign_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId) as unknown as PlayFeedEventRow[];

  const page = rows.slice(cursor, cursor + limit);

  sendJson(res, 200, {
    events: page.map((row) => ({ event_id: row.event_id, text: row.text, sequence: row.sequence })),
    next_cursor: cursor + page.length,
  });
}
