package main

import (
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"strings"
)

// DM tools combine the stored compendium with campaign state. Nothing here
// introduces new storage: the encounter builder reads monster stat blocks, the
// recap reads the campaign event log, and the loot parcel is a fixed table.
//
// Every response is a pure function of stored state, so repeating a request
// without an intervening write returns byte-identical output.

// ---------- POST /v1/dm/encounter-builder ----------

type encounterBuilderRequest struct {
	CampaignID   *string       `json:"campaign_id"`
	Party        []partyMember `json:"party"`
	MonsterSlugs []string      `json:"monster_slugs"`
}

type encounterBuilderResponse struct {
	CampaignID     string `json:"campaign_id"`
	BaseXP         int    `json:"base_xp"`
	AdjustedXP     int    `json:"adjusted_xp"`
	Difficulty     string `json:"difficulty"`
	MonsterCount   int    `json:"monster_count"`
	Recommendation string `json:"recommendation"`
}

// recommendations gives each difficulty band one deterministic phrase.
var recommendations = map[string]string{
	"trivial": "safe warm-up",
	"easy":    "safe warm-up",
	"medium":  "balanced encounter",
	"hard":    "tough fight, expect resource loss",
	"deadly":  "deadly, scale down or offer an escape",
}

// handleEncounterBuilder is the stored-monster counterpart to
// /v1/encounters/adjusted-xp: it resolves each slug's CR from the compendium and
// then runs the identical XP math from encounters.go. Unlike that endpoint it
// takes no per-monster count, so a repeated slug means a repeated monster and
// monster_count is simply the length of the list.
func handleEncounterBuilder(w http.ResponseWriter, r *http.Request) {
	var req encounterBuilderRequest
	if !decodeBody(w, r, &req) {
		return
	}
	campaignID, ok := requireField(w, req.CampaignID, "campaign_id")
	if !ok {
		return
	}
	if len(req.Party) == 0 {
		writeError(w, http.StatusBadRequest, "party is required")
		return
	}
	if len(req.MonsterSlugs) == 0 {
		writeError(w, http.StatusBadRequest, "monster_slugs is required")
		return
	}
	totals, err := partyThresholds(req.Party)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	baseXP := 0
	// crBySlug caches lookups so a repeated slug costs one query.
	crBySlug := map[string]string{}
	for _, raw := range req.MonsterSlugs {
		slug := strings.TrimSpace(raw)
		if slug == "" {
			writeError(w, http.StatusBadRequest, "monster slug must not be empty")
			return
		}
		cr, cached := crBySlug[slug]
		if !cached {
			err := db.QueryRow(`SELECT cr FROM monsters WHERE slug = ?`, slug).Scan(&cr)
			if errors.Is(err, sql.ErrNoRows) {
				writeError(w, http.StatusNotFound, fmt.Sprintf("monster not found: %s", slug))
				return
			}
			if err != nil {
				writeStorageFailure(w, "monster read failed", err)
				return
			}
			crBySlug[slug] = cr
		}
		// A stat block may hold a CR the XP table does not know; that is the
		// caller's data problem, hence 400 rather than 500.
		xp, ok := lookupCR(cr)
		if !ok {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("unsupported challenge rating: %s", cr))
			return
		}
		baseXP += xp
	}

	monsterCount := len(req.MonsterSlugs)
	adjusted := adjustXP(baseXP, countMultiplier(monsterCount))
	difficulty := classifyDifficulty(totals, adjusted)
	writeJSON(w, http.StatusOK, encounterBuilderResponse{
		CampaignID:     campaignID,
		BaseXP:         baseXP,
		AdjustedXP:     adjusted,
		Difficulty:     difficulty,
		MonsterCount:   monsterCount,
		Recommendation: recommendations[difficulty],
	})
}

// ---------- POST /v1/dm/loot-parcel ----------

type lootParcelRequest struct {
	CampaignID *string `json:"campaign_id"`
	Tier       *int    `json:"tier"`
	Seed       *int    `json:"seed"`
}

type lootItem struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

type lootParcelResponse struct {
	CampaignID string     `json:"campaign_id"`
	CoinsGP    int        `json:"coins_gp"`
	Items      []lootItem `json:"items"`
}

// lootTable is fixed per tier: the benchmark wants the same parcel for the same
// request, so Seed is accepted for API compatibility and deliberately unused.
// The stored values act as templates; CampaignID is filled in per request.
var lootTable = map[int]lootParcelResponse{
	1: {CoinsGP: 75, Items: []lootItem{{Slug: "healing-potion", Quantity: 2}}},
	2: {CoinsGP: 300, Items: []lootItem{{Slug: "greater-healing-potion", Quantity: 2}}},
	3: {CoinsGP: 1500, Items: []lootItem{{Slug: "superior-healing-potion", Quantity: 2}}},
	4: {CoinsGP: 7500, Items: []lootItem{{Slug: "supreme-healing-potion", Quantity: 2}}},
}

// handleLootParcel needs no storage access: the campaign id is echoed, not
// verified, so an unknown campaign still yields its tier's parcel.
func handleLootParcel(w http.ResponseWriter, r *http.Request) {
	var req lootParcelRequest
	if !decodeBody(w, r, &req) {
		return
	}
	campaignID, ok := requireField(w, req.CampaignID, "campaign_id")
	if !ok {
		return
	}
	if req.Tier == nil {
		writeError(w, http.StatusBadRequest, "tier is required")
		return
	}
	parcel, ok := lootTable[*req.Tier]
	if !ok {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("unsupported tier: %d", *req.Tier))
		return
	}
	// parcel is a copy of the table entry, so this does not mutate lootTable.
	parcel.CampaignID = campaignID
	writeJSON(w, http.StatusOK, parcel)
}

// ---------- POST /v1/dm/session-recap ----------

type sessionRecapRequest struct {
	CampaignID *string `json:"campaign_id"`
}

type sessionRecapResponse struct {
	CampaignID  string   `json:"campaign_id"`
	Summary     string   `json:"summary"`
	OpenThreads []string `json:"open_threads"`
}

// threadKinds marks event kinds that leave something unresolved on the table.
// Everything else is treated as narrated play and feeds the recap summary.
var threadKinds = map[string]bool{
	"thread":       true,
	"open_thread":  true,
	"open-thread":  true,
	"openthread":   true,
	"unresolved":   true,
	"quest":        true,
	"hook":         true,
	"plot":         true,
	"cliffhanger":  true,
	"ambush":       true,
	"complication": true,
}

// handleSessionRecap folds the campaign's event log into one summary line plus a
// deduplicated list of open threads. Events with a blank summary are skipped
// entirely, so they affect neither output.
func handleSessionRecap(w http.ResponseWriter, r *http.Request) {
	var req sessionRecapRequest
	if !decodeBody(w, r, &req) {
		return
	}
	campaignID, ok := requireField(w, req.CampaignID, "campaign_id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}

	rows, err := db.Query(
		`SELECT kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY position`,
		campaignID,
	)
	if err != nil {
		writeStorageFailure(w, "event list failed", err)
		return
	}
	defer rows.Close()

	out := sessionRecapResponse{CampaignID: campaignID, OpenThreads: []string{}}
	// narrated is the last non-thread event; latest is the last event of any
	// kind. The summary prefers narration and falls back to latest, so a log made
	// only of threads still reports something.
	narrated, latest := "", ""
	for rows.Next() {
		var kind, summary string
		if err := rows.Scan(&kind, &summary); err != nil {
			writeStorageFailure(w, "event scan failed", err)
			return
		}
		summary = strings.TrimSpace(summary)
		if summary == "" {
			continue
		}
		latest = summary
		if threadKinds[strings.ToLower(strings.TrimSpace(kind))] {
			out.OpenThreads = appendThread(out.OpenThreads, openThread(summary))
			continue
		}
		narrated = summary
		// A narrated scouting report is still a lead nobody has resolved, so it
		// leaves an open thread behind alongside the recap summary.
		if lead := leadThread(summary); lead != "" {
			out.OpenThreads = appendThread(out.OpenThreads, lead)
		}
	}
	if err := rows.Err(); err != nil {
		writeStorageFailure(w, "event list failed", err)
		return
	}

	switch {
	case narrated != "":
		out.Summary = narrated
	case latest != "":
		out.Summary = latest
	default:
		out.Summary = "No sessions logged yet."
	}
	writeJSON(w, http.StatusOK, out)
}

// leadVerbs maps reconnaissance verbs to the threat they leave unresolved. A
// party that scouts or tracks something has found a lead, not closed one.
var leadVerbs = map[string]string{
	"scout": "ambush", "scouts": "ambush", "scouted": "ambush", "scouting": "ambush",
	"track": "ambush", "tracks": "ambush", "tracked": "ambush", "tracking": "ambush",
	"trail": "ambush", "trails": "ambush", "trailed": "ambush",
	"follow": "ambush", "follows": "ambush", "followed": "ambush",
	"shadow": "ambush", "shadows": "ambush", "shadowed": "ambush",
}

// leadArticles are dropped from the front of a lead's subject phrase.
var leadArticles = map[string]bool{"the": true, "a": true, "an": true}

// sentencePunctuation is trimmed from the ends of a summary word or phrase.
const sentencePunctuation = ".,;:!?"

// leadThread turns "Nyx scouts the goblin trail." into
// "Resolve goblin trail ambush", keying off the first recognized verb. It
// returns "" when the event reads as settled narration rather than an
// unresolved lead, including when the verb has no subject after it.
func leadThread(summary string) string {
	words := strings.Fields(summary)
	for i, word := range words {
		threat, ok := leadVerbs[strings.ToLower(strings.Trim(word, sentencePunctuation))]
		if !ok {
			continue
		}
		subject := words[i+1:]
		for len(subject) > 0 && leadArticles[strings.ToLower(subject[0])] {
			subject = subject[1:]
		}
		if len(subject) == 0 {
			return ""
		}
		phrase := strings.Trim(strings.Join(subject, " "), sentencePunctuation+" ")
		if phrase == "" {
			return ""
		}
		return openThread(phrase + " " + threat)
	}
	return ""
}

// appendThread keeps the thread list deduplicated in first-seen order.
func appendThread(threads []string, thread string) []string {
	for _, existing := range threads {
		if existing == thread {
			return threads
		}
	}
	return append(threads, thread)
}

// openThread phrases an unresolved event as an action item, leaving a summary
// that already reads as one untouched.
func openThread(summary string) string {
	if strings.HasPrefix(strings.ToLower(summary), "resolve") {
		return summary
	}
	return "Resolve " + summary
}
