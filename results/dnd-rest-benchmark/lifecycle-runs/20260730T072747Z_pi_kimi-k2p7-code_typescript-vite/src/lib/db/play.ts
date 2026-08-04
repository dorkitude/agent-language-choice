// Play-mode campaign persistence (lobby/active turn-based play surface).

import { db } from './connection.js';
import type {
  Action,
  CampaignDocument,
  CombatAction,
  Condition,
  Encounter,
  Location,
  LocationConnection,
  LocationEvent,
  Narration,
  PlayCampaign,
  PlayCampaignMember,
  PlayScene,
  Resolution,
  Rest,
  RosterMonster,
  Travel,
} from '../types.js';

export function createPlayCampaign(campaign: PlayCampaign): void {
  db.prepare('INSERT INTO play_campaigns (id, name, owner, status, max_players, nudge_count) VALUES (?, ?, ?, ?, ?, ?)').run(
    campaign.id,
    campaign.name,
    campaign.owner,
    campaign.status,
    campaign.max_players,
    campaign.nudge_count ?? 0,
  );
}

export function getPlayCampaign(id: string): PlayCampaign | undefined {
  const row = db.prepare('SELECT id, name, owner, status, max_players, current_actor, turn_number, nudge_count, current_location_id FROM play_campaigns WHERE id = ?').get(id) as
    | { id: string; name: string; owner: string; status: 'lobby' | 'active'; max_players: number; current_actor: string | null; turn_number: number | null; nudge_count: number | null; current_location_id: string | null }
    | undefined;
  if (!row) return undefined;
  return {
    id: row.id,
    name: row.name,
    owner: row.owner,
    status: row.status,
    max_players: row.max_players,
    current_actor: row.current_actor ?? undefined,
    turn_number: row.turn_number ?? undefined,
    nudge_count: row.nudge_count ?? undefined,
    current_location_id: row.current_location_id ?? undefined,
  };
}

export function playCampaignExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM play_campaigns WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function createPlayCampaignMember(member: PlayCampaignMember): void {
  const nextRow = db.prepare(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM play_campaign_members WHERE campaign_id = ?',
  ).get(member.campaign_id) as { next_seq: number } | undefined;
  const sequence = nextRow?.next_seq ?? 1;
  const hpMax = member.hp_max ?? 20;
  const hpCurrent = member.hp_current ?? hpMax;
  const status = hpCurrent > 0 ? 'alive' : 'unconscious';
  db.prepare(
    'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, sequence, hp_max, hp_current, status, death_successes, death_failures) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).run(member.campaign_id, member.username, member.character_id, member.name, member.class, sequence, hpMax, hpCurrent, status, 0, 0);
}

export function countPlayCampaignMembers(campaignId: string): number {
  const row = db.prepare('SELECT COUNT(*) as cnt FROM play_campaign_members WHERE campaign_id = ?').get(campaignId) as
    | { cnt: number }
    | undefined;
  return row ? row.cnt : 0;
}

export function getPlayCampaignMemberByPlayer(campaignId: string, username: string): PlayCampaignMember | undefined {
  const row = db
    .prepare('SELECT campaign_id, username, character_id, name, class, hp_max, hp_current, status, death_successes, death_failures FROM play_campaign_members WHERE campaign_id = ? AND username = ?')
    .get(campaignId, username) as
    | { campaign_id: string; username: string; character_id: string; name: string; class: string; hp_max: number; hp_current: number; status: 'alive' | 'unconscious' | 'stable' | 'dead'; death_successes: number; death_failures: number }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function getPlayCampaignMembers(campaignId: string): PlayCampaignMember[] {
  return db
    .prepare('SELECT campaign_id, username, character_id, name, class, sequence, hp_max, hp_current, status, death_successes, death_failures FROM play_campaign_members WHERE campaign_id = ? ORDER BY sequence')
    .all(campaignId) as PlayCampaignMember[];
}

export function startPlayCampaign(campaignId: string, currentActor: string, turnNumber: number): void {
  db.prepare('UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ? WHERE id = ?').run(
    'active',
    currentActor,
    turnNumber,
    campaignId,
  );
}

export function getPlayCampaignMemberByCharacterId(characterId: string): PlayCampaignMember | undefined {
  const row = db
    .prepare('SELECT campaign_id, username, character_id, name, class, hp_max, hp_current, status, death_successes, death_failures FROM play_campaign_members WHERE character_id = ?')
    .get(characterId) as
    | { campaign_id: string; username: string; character_id: string; name: string; class: string; hp_max: number; hp_current: number; status: 'alive' | 'unconscious' | 'stable' | 'dead'; death_successes: number; death_failures: number }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function getPlayCampaignDocument(campaignId: string): CampaignDocument | undefined {
  const row = db.prepare('SELECT campaign_id, story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?').get(campaignId) as
    | { campaign_id: string; story: string; dm_notes: string }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function upsertPlayCampaignDocument(campaignId: string, story: string, dm_notes: string): CampaignDocument {
  db.prepare(`
    INSERT INTO play_campaign_documents (campaign_id, story, dm_notes)
    VALUES (?, ?, ?)
    ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes
  `).run(campaignId, story, dm_notes);
  return { campaign_id: campaignId, story, dm_notes };
}

function getNextPlayEventSequence(campaignId: string): number {
  const row = db.prepare(`
    SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM (
      SELECT sequence FROM play_narrations WHERE campaign_id = ?
      UNION ALL
      SELECT sequence FROM play_actions WHERE campaign_id = ?
      UNION ALL
      SELECT sequence FROM play_resolutions WHERE campaign_id = ?
      UNION ALL
      SELECT sequence FROM play_travels WHERE campaign_id = ?
      UNION ALL
      SELECT sequence FROM play_location_events WHERE campaign_id = ?
      UNION ALL
      SELECT sequence FROM play_rests WHERE campaign_id = ?
      UNION ALL
      SELECT sequence FROM play_combat_actions WHERE campaign_id = ?
    )
  `).get(campaignId, campaignId, campaignId, campaignId, campaignId, campaignId, campaignId) as { next_seq: number } | undefined;
  return row?.next_seq ?? 1;
}

export function createPlayNarration(campaignId: string, actor: string, text: string): Narration {
  const sequence = getNextPlayEventSequence(campaignId);
  const row = db.prepare(`
    INSERT INTO play_narrations (campaign_id, sequence, actor, text)
    VALUES (?, ?, ?, ?)
    RETURNING sequence, actor, text
  `).get(campaignId, sequence, actor, text) as { sequence: number; actor: string; text: string };
  return { sequence: row.sequence, campaign_id: campaignId, actor: row.actor, text: row.text };
}

export function getPlayNarrationsByCampaign(campaignId: string): Narration[] {
  const rows = db
    .prepare('SELECT campaign_id, sequence, actor, text FROM play_narrations WHERE campaign_id = ? ORDER BY sequence')
    .all(campaignId) as { campaign_id: string; sequence: number; actor: string; text: string }[];
  return rows.map((row) => ({ sequence: row.sequence, campaign_id: row.campaign_id, actor: row.actor, text: row.text }));
}

export function createPlayAction(campaignId: string, actor: string, type: string, text: string): Action {
  const sequence = getNextPlayEventSequence(campaignId);
  const row = db.prepare(`
    INSERT INTO play_actions (campaign_id, sequence, actor, type, text)
    VALUES (?, ?, ?, ?, ?)
    RETURNING sequence, actor, type, text
  `).get(campaignId, sequence, actor, type, text) as { sequence: number; actor: string; type: string; text: string };
  return { sequence: row.sequence, campaign_id: campaignId, actor: row.actor, type: row.type, text: row.text };
}

export function getPlayActionsByCampaign(campaignId: string): Action[] {
  const rows = db
    .prepare('SELECT campaign_id, sequence, actor, type, text FROM play_actions WHERE campaign_id = ? ORDER BY sequence')
    .all(campaignId) as { campaign_id: string; sequence: number; actor: string; type: string; text: string }[];
  return rows.map((row) => ({ sequence: row.sequence, campaign_id: row.campaign_id, actor: row.actor, type: row.type, text: row.text }));
}

export function createCombatAction(campaignId: string, encounterId: string, actor: string, type: string, target: string, text: string): CombatAction {
  const sequence = getNextPlayEventSequence(campaignId);
  const row = db.prepare(`
    INSERT INTO play_combat_actions (campaign_id, encounter_id, sequence, actor, type, target, text)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    RETURNING sequence, actor, type, target, text
  `).get(campaignId, encounterId, sequence, actor, type, target, text) as { sequence: number; actor: string; type: string; target: string; text: string };
  return { sequence: row.sequence, campaign_id: campaignId, encounter_id: encounterId, actor: row.actor, type: row.type, target: row.target, text: row.text };
}

export function getCombatActionsByCampaign(campaignId: string): CombatAction[] {
  const rows = db
    .prepare('SELECT campaign_id, encounter_id, sequence, actor, type, target, text FROM play_combat_actions WHERE campaign_id = ? ORDER BY sequence')
    .all(campaignId) as { campaign_id: string; encounter_id: string; sequence: number; actor: string; type: string; target: string; text: string }[];
  return rows.map((row) => ({ sequence: row.sequence, campaign_id: row.campaign_id, encounter_id: row.encounter_id, actor: row.actor, type: row.type, target: row.target, text: row.text }));
}

export function createPlayResolution(campaignId: string, actor: string, text: string): Resolution {
  const sequence = getNextPlayEventSequence(campaignId);
  const row = db.prepare(`
    INSERT INTO play_resolutions (campaign_id, sequence, actor, text)
    VALUES (?, ?, ?, ?)
    RETURNING sequence, actor, text
  `).get(campaignId, sequence, actor, text) as { sequence: number; actor: string; text: string };
  return { sequence: row.sequence, campaign_id: campaignId, actor: row.actor, text: row.text };
}

export function getPlayResolutionsByCampaign(campaignId: string): Resolution[] {
  const rows = db
    .prepare('SELECT campaign_id, sequence, actor, text FROM play_resolutions WHERE campaign_id = ? ORDER BY sequence')
    .all(campaignId) as { campaign_id: string; sequence: number; actor: string; text: string }[];
  return rows.map((row) => ({ sequence: row.sequence, campaign_id: row.campaign_id, actor: row.actor, text: row.text }));
}

export function createPlayTravel(campaignId: string, actor: string, destinationId: string, travelTurns: number): Travel {
  const sequence = getNextPlayEventSequence(campaignId);
  const row = db.prepare(`
    INSERT INTO play_travels (campaign_id, sequence, actor, destination_id, travel_turns)
    VALUES (?, ?, ?, ?, ?)
    RETURNING sequence, actor, destination_id, travel_turns
  `).get(campaignId, sequence, actor, destinationId, travelTurns) as { sequence: number; actor: string; destination_id: string; travel_turns: number };
  return { sequence: row.sequence, campaign_id: campaignId, actor: row.actor, destination_id: row.destination_id, travel_turns: row.travel_turns };
}

export function getPlayTravelsByCampaign(campaignId: string): Travel[] {
  const rows = db
    .prepare('SELECT campaign_id, sequence, actor, destination_id, travel_turns FROM play_travels WHERE campaign_id = ? ORDER BY sequence')
    .all(campaignId) as { campaign_id: string; sequence: number; actor: string; destination_id: string; travel_turns: number }[];
  return rows.map((row) => ({ sequence: row.sequence, campaign_id: row.campaign_id, actor: row.actor, destination_id: row.destination_id, travel_turns: row.travel_turns }));
}

export function createPlayRest(campaignId: string, actor: string, type: 'short' | 'long', hpCurrent: number, hpMax: number): Rest {
  const sequence = getNextPlayEventSequence(campaignId);
  const row = db.prepare(`
    INSERT INTO play_rests (campaign_id, sequence, actor, type, hp_current, hp_max)
    VALUES (?, ?, ?, ?, ?, ?)
    RETURNING sequence, actor, type, hp_current, hp_max
  `).get(campaignId, sequence, actor, type, hpCurrent, hpMax) as { sequence: number; actor: string; type: 'short' | 'long'; hp_current: number; hp_max: number };
  return { sequence: row.sequence, campaign_id: campaignId, actor: row.actor, type: row.type, hp_current: row.hp_current, hp_max: row.hp_max };
}

export function getPlayRestsByCampaign(campaignId: string): Rest[] {
  const rows = db
    .prepare('SELECT campaign_id, sequence, actor, type, hp_current, hp_max FROM play_rests WHERE campaign_id = ? ORDER BY sequence')
    .all(campaignId) as { campaign_id: string; sequence: number; actor: string; type: 'short' | 'long'; hp_current: number; hp_max: number }[];
  return rows.map((row) => ({ sequence: row.sequence, campaign_id: row.campaign_id, actor: row.actor, type: row.type, hp_current: row.hp_current, hp_max: row.hp_max }));
}

export function createEncounter(encounter: Encounter): void {
  db.prepare('INSERT INTO play_encounters (campaign_id, id, name, status, round, turn_index, combatants) VALUES (?, ?, ?, ?, ?, ?, ?)').run(
    encounter.campaign_id,
    encounter.id,
    encounter.name,
    encounter.status,
    encounter.round ?? 1,
    encounter.turn_index ?? 0,
    JSON.stringify(encounter.combatants),
  );
}

export function getEncounter(campaignId: string, id: string): Encounter | undefined {
  const row = db.prepare('SELECT campaign_id, id, name, status, round, turn_index, combatants FROM play_encounters WHERE campaign_id = ? AND id = ?').get(campaignId, id) as
    | { campaign_id: string; id: string; name: string; status: 'active'; round: number; turn_index: number; combatants: string }
    | undefined;
  if (!row) return undefined;
  return { ...row, combatants: JSON.parse(row.combatants) as RosterMonster[] };
}

export function getActiveEncounter(campaignId: string): Encounter | undefined {
  const row = db.prepare('SELECT campaign_id, id, name, status, round, turn_index, combatants FROM play_encounters WHERE campaign_id = ? AND status = ?').get(campaignId, 'active') as
    | { campaign_id: string; id: string; name: string; status: 'active'; round: number; turn_index: number; combatants: string }
    | undefined;
  if (!row) return undefined;
  return { ...row, combatants: JSON.parse(row.combatants) as RosterMonster[] };
}

export function addEncounterMonster(campaignId: string, encounterId: string, monster: RosterMonster): void {
  const enc = getEncounter(campaignId, encounterId);
  if (!enc) return;
  if (enc.combatants.some((c) => c.monster_id === monster.monster_id)) {
    throw new Error('duplicate monster_id');
  }
  const hasExplicitOrder = enc.combatants.some((c) => c.sequence !== undefined);
  if (hasExplicitOrder) {
    const maxSequence = Math.max(0, ...enc.combatants.map((c) => c.sequence ?? 0));
    monster.sequence = maxSequence + 1;
  }
  const combatants = [...enc.combatants, monster];
  db.prepare('UPDATE play_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(combatants),
    campaignId,
    encounterId,
  );
}

export function removeEncounterMonster(campaignId: string, encounterId: string, monsterId: string): boolean {
  const enc = getEncounter(campaignId, encounterId);
  if (!enc) return false;
  const remaining = enc.combatants.filter((c) => c.monster_id !== monsterId);
  if (remaining.length === enc.combatants.length) return false;
  db.prepare('UPDATE play_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(remaining),
    campaignId,
    encounterId,
  );
  return true;
}

export function addEncounterMember(
  campaignId: string,
  encounterId: string,
  member: PlayCampaignMember,
  initiative: number,
): void {
  const enc = getEncounter(campaignId, encounterId);
  if (!enc) throw new Error('encounter not found');
  if (enc.combatants.some((c) => c.member === member.username)) {
    throw new Error('duplicate member');
  }
  const hasExplicitOrder = enc.combatants.some((c) => c.sequence !== undefined);
  const sequence = hasExplicitOrder ? Math.max(0, ...enc.combatants.map((c) => c.sequence ?? 0)) + 1 : undefined;
  const combatants = [
    ...enc.combatants,
    {
      member: member.username,
      character_id: member.character_id,
      name: member.name,
      initiative,
      sequence,
    },
  ];
  db.prepare('UPDATE play_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(combatants),
    campaignId,
    encounterId,
  );
}

export function removeEncounterMember(campaignId: string, encounterId: string, username: string): boolean {
  const enc = getEncounter(campaignId, encounterId);
  if (!enc) return false;
  if (!enc.combatants.some((c) => c.member === username)) return false;
  const remaining = enc.combatants.filter((c) => c.member !== username);
  db.prepare('UPDATE play_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(remaining),
    campaignId,
    encounterId,
  );
  return true;
}

export function encounterExists(campaignId: string, id: string): boolean {
  const row = db.prepare('SELECT 1 FROM play_encounters WHERE campaign_id = ? AND id = ?').get(campaignId, id) as { '1': number } | undefined;
  return row !== undefined;
}

export function updateEncounterMonsterHp(campaignId: string, encounterId: string, monsterId: string, hpCurrent: number): void {
  const enc = getEncounter(campaignId, encounterId);
  if (!enc) throw new Error('encounter not found');
  const combatants = enc.combatants.map((c) => (c.monster_id === monsterId ? { ...c, hp_current: hpCurrent } : c));
  db.prepare('UPDATE play_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(combatants),
    campaignId,
    encounterId,
  );
}

export function getEncounterTurnOrder(combatants: RosterMonster[]): RosterMonster[] {
  return [...combatants].sort((a, b) => {
    const seqA = a.sequence ?? 0;
    const seqB = b.sequence ?? 0;
    if (seqA !== seqB) return seqA - seqB;
    const initDiff = b.initiative - a.initiative;
    if (initDiff !== 0) return initDiff;
    return a.name.localeCompare(b.name);
  });
}

export function getEncounterActiveCombatant(encounter: Encounter): RosterMonster | undefined {
  const order = getEncounterTurnOrder(encounter.combatants);
  if (order.length === 0) return undefined;
  const index = Math.max(0, Math.min(encounter.turn_index, order.length - 1));
  return order[index];
}

export function advanceEncounterTurn(campaignId: string, encounterId: string): Encounter {
  const enc = getEncounter(campaignId, encounterId);
  if (!enc) throw new Error('encounter not found');
  const count = enc.combatants.length;
  let nextIndex = count === 0 ? 0 : (enc.turn_index + 1) % count;
  let nextRound = enc.round;
  if (count > 0 && nextIndex === 0) {
    nextRound += 1;
  }
  db.prepare('UPDATE play_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?').run(
    nextRound,
    nextIndex,
    campaignId,
    encounterId,
  );
  return getEncounter(campaignId, encounterId)!;
}

export function createPlayLocationEvent(campaignId: string, actor: string, locationId: string, name: string): LocationEvent {
  const sequence = getNextPlayEventSequence(campaignId);
  const row = db.prepare(`
    INSERT INTO play_location_events (campaign_id, sequence, actor, location_id, name)
    VALUES (?, ?, ?, ?, ?)
    RETURNING sequence, actor, location_id, name
  `).get(campaignId, sequence, actor, locationId, name) as { sequence: number; actor: string; location_id: string; name: string };
  return { sequence: row.sequence, campaign_id: campaignId, actor: row.actor, location_id: row.location_id, name: row.name };
}

export function getPlayLocationEventsByCampaign(campaignId: string): LocationEvent[] {
  const rows = db
    .prepare('SELECT campaign_id, sequence, actor, location_id, name FROM play_location_events WHERE campaign_id = ? ORDER BY sequence')
    .all(campaignId) as { campaign_id: string; sequence: number; actor: string; location_id: string; name: string }[];
  return rows.map((row) => ({ sequence: row.sequence, campaign_id: row.campaign_id, actor: row.actor, location_id: row.location_id, name: row.name }));
}

export type PlayEvent =
  | { sequence: number; kind: 'narration'; actor: string; text: string }
  | { sequence: number; kind: 'action'; actor: string; type: string; text: string }
  | { sequence: number; kind: 'combat_action'; actor: string; type: string; target: string; text: string }
  | { sequence: number; kind: 'resolution'; actor: string; text: string }
  | { sequence: number; kind: 'travel'; actor: string; destination_id: string; travel_turns: number }
  | { sequence: number; kind: 'rest'; actor: string; type: 'short' | 'long'; hp_current: number; hp_max: number }
  | { sequence: number; kind: 'location'; actor: string; location_id: string; name: string };

export function getPlayEventsByCampaign(campaignId: string): PlayEvent[] {
  const narrations = getPlayNarrationsByCampaign(campaignId).map((n) => ({
    sequence: n.sequence,
    kind: 'narration' as const,
    actor: n.actor,
    text: n.text,
  }));
  const actions = getPlayActionsByCampaign(campaignId).map((a) => ({
    sequence: a.sequence,
    kind: 'action' as const,
    actor: a.actor,
    type: a.type,
    text: a.text,
  }));
  const resolutions = getPlayResolutionsByCampaign(campaignId).map((r) => ({
    sequence: r.sequence,
    kind: 'resolution' as const,
    actor: r.actor,
    text: r.text,
  }));
  const travels = getPlayTravelsByCampaign(campaignId).map((t) => ({
    sequence: t.sequence,
    kind: 'travel' as const,
    actor: t.actor,
    destination_id: t.destination_id,
    travel_turns: t.travel_turns,
  }));
  const locations = getPlayLocationEventsByCampaign(campaignId).map((l) => ({
    sequence: l.sequence,
    kind: 'location' as const,
    actor: l.actor,
    location_id: l.location_id,
    name: l.name,
  }));
  const rests = getPlayRestsByCampaign(campaignId).map((r) => ({
    sequence: r.sequence,
    kind: 'rest' as const,
    actor: r.actor,
    type: r.type,
    hp_current: r.hp_current,
    hp_max: r.hp_max,
  }));
  const combatActions = getCombatActionsByCampaign(campaignId).map((a) => ({
    sequence: a.sequence,
    kind: 'combat_action' as const,
    actor: a.actor,
    type: a.type,
    target: a.target,
    text: a.text,
  }));
  return [...narrations, ...actions, ...combatActions, ...resolutions, ...travels, ...locations, ...rests].sort((a, b) => a.sequence - b.sequence);
}

export function setPlayCampaignCurrentActor(campaignId: string, currentActor: string): void {
  db.prepare('UPDATE play_campaigns SET current_actor = ? WHERE id = ?').run(currentActor, campaignId);
}

export function setPlayCampaignCurrentLocation(campaignId: string, locationId: string): void {
  db.prepare('UPDATE play_campaigns SET current_location_id = ? WHERE id = ?').run(locationId, campaignId);
}

export function setEncounterCombatants(
  campaignId: string,
  encounterId: string,
  combatants: RosterMonster[],
  turnIndex?: number,
): void {
  if (turnIndex !== undefined) {
    db.prepare('UPDATE play_encounters SET combatants = ?, turn_index = ? WHERE campaign_id = ? AND id = ?').run(
      JSON.stringify(combatants),
      turnIndex,
      campaignId,
      encounterId,
    );
  } else {
    db.prepare('UPDATE play_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?').run(
      JSON.stringify(combatants),
      campaignId,
      encounterId,
    );
  }
}

export function setPlayCampaignMemberHp(campaignId: string, username: string, hpCurrent: number): void {
  const status = hpCurrent > 0 ? 'alive' : 'unconscious';
  db.prepare('UPDATE play_campaign_members SET hp_current = ?, status = ?, death_successes = 0, death_failures = 0 WHERE campaign_id = ? AND username = ?').run(
    hpCurrent,
    status,
    campaignId,
    username,
  );
}

export function recordDeathSave(characterId: string, outcome: 'success' | 'failure'): PlayCampaignMember | undefined {
  const member = getPlayCampaignMemberByCharacterId(characterId);
  if (!member) return undefined;
  let successes = member.death_successes ?? 0;
  let failures = member.death_failures ?? 0;
  if (outcome === 'success') {
    successes = Math.min(3, successes + 1);
  } else {
    failures = Math.min(3, failures + 1);
  }
  const status: 'unconscious' | 'stable' | 'dead' = failures >= 3 ? 'dead' : successes >= 3 ? 'stable' : 'unconscious';
  db.prepare('UPDATE play_campaign_members SET death_successes = ?, death_failures = ?, status = ? WHERE character_id = ?').run(
    successes,
    failures,
    status,
    characterId,
  );
  return getPlayCampaignMemberByCharacterId(characterId);
}

export function advancePlayCampaign(campaignId: string, nextActor: string, turnNumber: number): void {
  db.prepare('UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?').run(nextActor, turnNumber, campaignId);
}

export function getPlayCampaignNudgeCount(campaignId: string): number {
  const row = db.prepare('SELECT nudge_count FROM play_campaigns WHERE id = ?').get(campaignId) as
    | { nudge_count: number }
    | undefined;
  return row ? row.nudge_count : 0;
}

export function incrementPlayCampaignNudgeCount(campaignId: string): number {
  db.prepare('UPDATE play_campaigns SET nudge_count = nudge_count + 1 WHERE id = ?').run(campaignId);
  return getPlayCampaignNudgeCount(campaignId);
}

export function createPlayScene(scene: PlayScene): void {
  db.prepare('INSERT INTO play_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)').run(
    scene.campaign_id,
    scene.id,
    scene.name,
    scene.status,
  );
}

export function getPlayScene(campaignId: string, sceneId: string): PlayScene | undefined {
  const row = db
    .prepare('SELECT campaign_id, id, name, status FROM play_scenes WHERE campaign_id = ? AND id = ?')
    .get(campaignId, sceneId) as
    | { campaign_id: string; id: string; name: string; status: 'open' | 'closed' }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function getPlayScenesByCampaign(campaignId: string): PlayScene[] {
  return db
    .prepare('SELECT campaign_id, id, name, status FROM play_scenes WHERE campaign_id = ? ORDER BY id')
    .all(campaignId) as PlayScene[];
}

export function closePlayScene(campaignId: string, sceneId: string): void {
  db.prepare('UPDATE play_scenes SET status = ? WHERE campaign_id = ? AND id = ?').run('closed', campaignId, sceneId);
}

export function setPlayCampaignCurrentScene(campaignId: string, sceneId: string): void {
  db.prepare('UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?').run(sceneId, campaignId);
}

export function getPlayCampaignCurrentScene(campaignId: string): PlayScene | undefined {
  const row = db
    .prepare(`
      SELECT s.campaign_id, s.id, s.name, s.status
      FROM play_scenes s
      JOIN play_campaigns c ON c.id = s.campaign_id AND c.current_scene_id = s.id
      WHERE c.id = ? AND s.status = 'open'
    `)
    .get(campaignId) as
    | { campaign_id: string; id: string; name: string; status: 'open' | 'closed' }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function createLocation(location: Location): void {
  db.prepare('INSERT INTO play_locations (campaign_id, id, name) VALUES (?, ?, ?)').run(
    location.campaign_id,
    location.id,
    location.name,
  );
}

export function getLocation(campaignId: string, id: string): Location | undefined {
  const row = db
    .prepare('SELECT campaign_id, id, name FROM play_locations WHERE campaign_id = ? AND id = ?')
    .get(campaignId, id) as
    | { campaign_id: string; id: string; name: string }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function getLocationsByCampaign(campaignId: string): Location[] {
  return db
    .prepare('SELECT campaign_id, id, name FROM play_locations WHERE campaign_id = ? ORDER BY id')
    .all(campaignId) as Location[];
}

export function createConnection(connection: LocationConnection): void {
  db.prepare('INSERT INTO play_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)').run(
    connection.campaign_id,
    connection.from_id,
    connection.to_id,
    connection.travel_turns,
  );
}

export function getConnection(campaignId: string, fromId: string, toId: string): LocationConnection | undefined {
  const row = db
    .prepare('SELECT campaign_id, from_id, to_id, travel_turns FROM play_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?')
    .get(campaignId, fromId, toId) as
    | { campaign_id: string; from_id: string; to_id: string; travel_turns: number }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function getConnectionsFrom(campaignId: string, fromId: string): LocationConnection[] {
  return db
    .prepare('SELECT campaign_id, from_id, to_id, travel_turns FROM play_location_connections WHERE campaign_id = ? AND from_id = ? ORDER BY to_id')
    .all(campaignId, fromId) as LocationConnection[];
}

export function getEncounterConditions(encounterId: string): Record<string, Condition[]> {
  const rows = db
    .prepare('SELECT target, condition, remaining_rounds FROM play_encounter_conditions WHERE encounter_id = ?')
    .all(encounterId) as { target: string; condition: string; remaining_rounds: number }[];
  const result: Record<string, Condition[]> = {};
  for (const row of rows) {
    if (!result[row.target]) result[row.target] = [];
    result[row.target].push({ condition: row.condition, remaining_rounds: row.remaining_rounds });
  }
  return result;
}

export function getEncounterConditionsForTarget(encounterId: string, target: string): Condition[] {
  const rows = db
    .prepare('SELECT condition, remaining_rounds FROM play_encounter_conditions WHERE encounter_id = ? AND target = ?')
    .all(encounterId, target) as { condition: string; remaining_rounds: number }[];
  return rows.map((row) => ({ condition: row.condition, remaining_rounds: row.remaining_rounds }));
}

export function addEncounterCondition(
  campaignId: string,
  encounterId: string,
  target: string,
  condition: string,
  remainingRounds: number,
): void {
  db.prepare(
    'INSERT INTO play_encounter_conditions (campaign_id, encounter_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, encounterId, target, condition, remainingRounds);
}

export function decrementEncounterConditions(encounterId: string, target: string): void {
  db.prepare(
    'UPDATE play_encounter_conditions SET remaining_rounds = remaining_rounds - 1 WHERE encounter_id = ? AND target = ?',
  ).run(encounterId, target);
  db.prepare(
    'DELETE FROM play_encounter_conditions WHERE encounter_id = ? AND target = ? AND remaining_rounds <= 0',
  ).run(encounterId, target);
}
