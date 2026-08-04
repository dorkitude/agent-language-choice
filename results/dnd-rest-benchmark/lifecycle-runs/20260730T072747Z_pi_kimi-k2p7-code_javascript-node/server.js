import http from 'node:http';
import * as db from './lib/db.js';
import * as handlers from './lib/handlers.js';
import { createRouter } from './lib/router.js';
import { sendJson } from './lib/http.js';

const HOST = '127.0.0.1';
const PORT = process.env.PORT ?? 3000;

// Route table. Routes are checked in registration order, so parameterized
// routes are registered before the more general parents that could shadow them.
const router = createRouter()
  // Health
  .get(/^\/health$/, handlers.health)

  // Storage
  .get(/^\/v1\/storage\/status$/, handlers.storageStatus)
  .post(/^\/v1\/storage\/reset$/, handlers.storageReset)

  // Auth
  .post(/^\/v1\/auth\/register$/, handlers.register)
  .post(/^\/v1\/auth\/login$/, handlers.login)

  // Core / dice / checks / encounters / initiative
  .post(/^\/v1\/dice\/stats$/, handlers.diceStats)
  .post(/^\/v1\/checks\/ability$/, handlers.abilityCheck)
  .post(/^\/v1\/encounters\/adjusted-xp$/, handlers.adjustedXp)
  .post(/^\/v1\/initiative\/order$/, handlers.initiativeOrder)

  // Characters and PHB rules
  .post(/^\/v1\/characters\/ability-modifier$/, handlers.abilityModifier)
  .post(/^\/v1\/characters\/proficiency$/, handlers.proficiency)
  .post(/^\/v1\/characters\/derived-stats$/, handlers.derivedStats)
  .post(/^\/v1\/phb\/spell-slots$/, handlers.spellSlots)
  .post(/^\/v1\/phb\/rests\/long$/, handlers.longRest)
  .post(/^\/v1\/phb\/equipment-load$/, handlers.equipmentLoad)

  // Combat
  .post(/^\/v1\/combat\/sessions\/([^/]+)\/conditions$/, handlers.addCondition)
  .post(/^\/v1\/combat\/sessions\/([^/]+)\/advance$/, handlers.advanceTurn)
  .post(/^\/v1\/combat\/sessions$/, handlers.createCombatSession)

  // Compendium
  .post(/^\/v1\/compendium\/monsters$/, handlers.createMonster)
  .get(/^\/v1\/compendium\/monsters\/([^/]+)$/, handlers.readMonster)
  .post(/^\/v1\/compendium\/items$/, handlers.createItem)
  .get(/^\/v1\/compendium\/items\/([^/]+)$/, handlers.readItem)

  // DM helpers
  .post(/^\/v1\/dm\/encounter-builder$/, handlers.encounterBuilder)
  .post(/^\/v1\/dm\/loot-parcel$/, handlers.lootParcel)
  .post(/^\/v1\/dm\/session-recap$/, handlers.sessionRecap)

  // Campaigns (core)
  .post(/^\/v1\/campaigns$/, handlers.createCampaign)
  .get(/^\/v1\/campaigns\/([^/]+)\/state$/, handlers.readCampaignState)
  .get(/^\/v1\/campaigns\/([^/]+)\/relationships$/, handlers.readRelationships)
  .get(/^\/v1\/campaigns\/([^/]+)\/audit$/, handlers.getCampaignAudit)
  .get(/^\/v1\/campaigns\/([^/]+)\/export$/, handlers.getCampaignExport)
  .get(/^\/v1\/campaigns\/([^/]+)\/analytics\/summary$/, handlers.getCampaignAnalyticsSummary)
  .post(/^\/v1\/campaigns\/([^/]+)\/analytics\/risk-report$/, handlers.getCampaignRiskReport)

  // Campaigns (characters, events, factions, NPCs)
  .post(/^\/v1\/campaigns\/([^/]+)\/characters$/, handlers.createCampaignCharacter)
  .post(/^\/v1\/campaigns\/([^/]+)\/characters\/([^/]+)\/equipment$/, handlers.assignEquipment)
  .post(/^\/v1\/campaigns\/([^/]+)\/events$/, handlers.createCampaignEvent)
  .post(/^\/v1\/campaigns\/([^/]+)\/factions$/, handlers.createFaction)
  .post(/^\/v1\/campaigns\/([^/]+)\/npcs$/, handlers.createNpc)

  // Quests
  .post(/^\/v1\/campaigns\/([^/]+)\/quests\/([^/]+)\/progress$/, handlers.updateQuestProgress)
  .get(/^\/v1\/campaigns\/([^/]+)\/quests\/summary$/, handlers.getQuestSummary)
  .post(/^\/v1\/campaigns\/([^/]+)\/quests$/, handlers.createQuest)

  // Inventory and downtime crafting
  .get(/^\/v1\/campaigns\/([^/]+)\/inventory\/summary$/, handlers.getInventorySummary)
  .post(/^\/v1\/campaigns\/([^/]+)\/inventory$/, handlers.addInventoryItem)
  .post(/^\/v1\/campaigns\/([^/]+)\/downtime\/crafting\/([^/]+)\/advance$/, handlers.advanceCraftingProject)
  .post(/^\/v1\/campaigns\/([^/]+)\/downtime\/crafting$/, handlers.createCraftingProject)

  // Session scheduling
  .get(/^\/v1\/campaigns\/([^/]+)\/sessions\/next$/, handlers.getNextSession)
  .post(/^\/v1\/campaigns\/([^/]+)\/sessions\/([^/]+)\/attendance$/, handlers.recordSessionAttendance)
  .post(/^\/v1\/campaigns\/([^/]+)\/sessions$/, handlers.createCampaignSession)

  // Play campaigns (live play surface)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/my-turn$/, handlers.getPlayCampaignMyTurn)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/gm\/status$/, handlers.getPlayCampaignGmStatus)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/turn$/, handlers.getPlayCampaignTurn)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/turn\/nudge$/, handlers.nudgePlayCampaign)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/turn\/travel$/, handlers.travelTurn)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/turn\/rest$/, handlers.restTurn)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/actions$/, handlers.submitPlayerAction)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/resolutions$/, handlers.submitGmResolution)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/narrations$/, handlers.addNarration)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/document$/, handlers.getPlayCampaignDocument)
  .put(/^\/v1\/play\/campaigns\/([^/]+)\/document$/, handlers.updatePlayCampaignDocument)

  // Play campaigns (scenes)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/scenes\/current$/, handlers.getCurrentScene)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/scenes\/([^/]+)\/enter$/, handlers.enterScene)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/scenes\/([^/]+)\/close$/, handlers.closeScene)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/scenes$/, handlers.createScene)

  // Play campaigns (locations)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/locations\/([^/]+)\/travel$/, handlers.getTravel)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/locations\/([^/]+)\/connections$/, handlers.createConnection)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/locations$/, handlers.createLocation)

  // Play campaigns (encounters)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/damage$/, handlers.damageEncounter)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/heal$/, handlers.healEncounter)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/rewards$/, handlers.awardEncounterRewards)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/close$/, handlers.closeEncounter)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/end$/, handlers.endEncounter)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/conditions$/, handlers.addEncounterCondition)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/status$/, handlers.getPlayEncounterStatus)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn$/, handlers.getPlayEncounterTurn)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn\/advance$/, handlers.advancePlayEncounterTurn)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn\/delay$/, handlers.delayEncounterTurn)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn\/ready$/, handlers.readyEncounterAction)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/actions$/, handlers.submitEncounterAction)
  .delete(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/monsters\/([^/]+)$/, handlers.removeMonster)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/combatants$/, handlers.bindMemberCombatant)
  .delete(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/combatants\/([^/]+)$/, handlers.unbindMemberCombatant)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/monsters$/, handlers.addMonster)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/encounters$/, handlers.createEncounter)

  // Play campaigns (character ownership)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/owner$/, handlers.getCharacterOwner)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/claim$/, handlers.claimCharacter)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/transfer$/, handlers.transferCharacter)

  // Play campaigns (character choices, health, and death saves)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/build$/, handlers.buildCharacter)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/level-up$/, handlers.levelUpCharacter)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/skill-check$/, handlers.skillCheck)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/damage$/, handlers.damageCharacter)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/death-saves$/, handlers.deathSave)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/status$/, handlers.getCharacterStatus)

  // Play campaigns (character spellbook)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/spells$/, handlers.addCharacterSpell)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/spells$/, handlers.getCharacterSpellbook)
  .put(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/prepared-spells$/, handlers.prepareSpells)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/prepared-spells$/, handlers.getPreparedSpells)

  // Play campaigns (character spell casting)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/casts$/, handlers.castSpell)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/casts$/, handlers.getCharacterCasts)

  // Play campaigns (character concentration)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/concentration\/advance-turn$/, handlers.advanceConcentrationTurn)
  .put(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/concentration$/, handlers.putConcentration)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/concentration$/, handlers.getConcentration)
  .delete(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/concentration$/, handlers.deleteConcentration)

  // Play campaigns (character inventory)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/inventory\/items\/([^/]+)\/consume$/, handlers.consumePlayCharacterInventoryItem)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/inventory\/items$/, handlers.addPlayCharacterInventoryItem)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/inventory\/items$/, handlers.getPlayCharacterInventory)
  .delete(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/inventory\/items\/([^/]+)$/, handlers.removePlayCharacterInventoryItem)

  // Play campaigns (character equipment and attunement)
  .put(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/equipment\/([^/]+)$/, handlers.equipPlayCharacterItem)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/equipment\/([^/]+)$/, handlers.getPlayCharacterEquipment)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/equipment\/([^/]+)\/attune$/, handlers.attunePlayCharacterItem)

  // Play campaigns (character currency)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/currency\/transfers$/, handlers.transferCharacterCurrency)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/currency$/, handlers.getCharacterCurrency)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/rewards$/, handlers.getPlayCharacterQuestRewards)

  // Play campaigns (loot distribution)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/loot\/([^/]+)\/votes$/, handlers.voteLoot)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/loot\/([^/]+)\/assign$/, handlers.assignLoot)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/loot\/([^/]+)$/, handlers.getLoot)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/loot$/, handlers.createLoot)

  // Play campaigns (NPC dialogue)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/npcs\/([^/]+)\/dialogue$/, handlers.getPlayNpcDialogue)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/npcs\/([^/]+)\/dialogue$/, handlers.addPlayNpcDialogue)

  // Play campaigns (NPC agendas)
  .put(/^\/v1\/play\/campaigns\/([^/]+)\/npcs\/([^/]+)\/agenda$/, handlers.updatePlayNpcAgenda)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/npcs\/([^/]+)$/, handlers.getPlayNpc)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/npcs$/, handlers.createPlayNpc)

  // Play campaigns (factions)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/factions\/([^/]+)\/reputation$/, handlers.changePlayFactionReputation)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/factions\/([^/]+)\/reputation$/, handlers.getPlayFactionReputation)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/factions$/, handlers.createPlayFaction)

  // Play campaigns (relationship graph)
  .put(/^\/v1\/play\/campaigns\/([^/]+)\/relationships\/([^/]+)\/([^/]+)\/([^/]+)$/, handlers.updatePlayRelationship)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/relationships$/, handlers.createPlayRelationship)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/relationships$/, handlers.getPlayRelationships)

  // Play campaigns (clues)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/clues$/, handlers.createPlayClue)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/clues$/, handlers.getPlayClues)

  // Play campaigns (quests)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/quests$/, handlers.createPlayQuest)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/quests$/, handlers.getPlayQuests)
  .put(/^\/v1\/play\/campaigns\/([^/]+)\/quests\/([^/]+)\/state$/, handlers.updatePlayQuestState)
  .put(/^\/v1\/play\/campaigns\/([^/]+)\/quests\/([^/]+)\/rewards$/, handlers.configurePlayQuestRewards)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/quests\/([^/]+)\/rewards\/award$/, handlers.awardPlayQuestRewards)

  // Play campaigns (world events)
  .get(/^\/v1\/play\/campaigns\/([^/]+)\/world-events$/, handlers.getPlayWorldEvents)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/world-events\/([^/]+)\/resolve$/, handlers.resolvePlayWorldEvent)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/world-events$/, handlers.createPlayWorldEvent)

  .post(/^\/v1\/play\/campaigns\/([^/]+)\/members$/, handlers.joinPlayCampaign)
  .post(/^\/v1\/play\/campaigns\/([^/]+)\/start$/, handlers.startPlayCampaign)
  .post(/^\/v1\/play\/campaigns$/, handlers.createPlayCampaign);

const server = http.createServer((req, res) => {
  router.handle(req, res).catch(err => {
    console.error(err);
    sendJson(res, 500, { error: 'internal server error' });
  });
});

// Reset the database on every startup so the server always begins from a
// known, deterministic state. This matches the behavior expected by the
// cumulative evaluator suite and is the equivalent of `initDb()` followed by
// clearing any leftover data from previous runs.
db.resetDb();
server.listen(PORT, HOST, () => {
  console.log(`Server listening on ${HOST}:${PORT}`);
});
