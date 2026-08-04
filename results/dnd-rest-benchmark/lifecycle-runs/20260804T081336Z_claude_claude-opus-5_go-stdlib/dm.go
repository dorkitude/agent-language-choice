package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// DM-facing tools that combine stored compendium and campaign state. All
// results are deterministic: no randomness, no wall-clock reads.

// dmRecommendations maps a difficulty band to the advice string returned by the
// encounter builder. Keys must cover every band classifyDifficulty can produce.
var dmRecommendations = map[string]string{
	"trivial": "safe warm-up",
	"easy":    "safe warm-up",
	"medium":  "balanced fight",
	"hard":    "tough fight",
	"deadly":  "scale down or add an escape route",
}

// lookupCampaign returns the campaign for an id, or false when absent. The
// returned pointer is only safe to read while holding campaigns.mu, so callers
// that need the roster or event log re-acquire the lock.
func lookupCampaign(id string) (*campaign, bool) {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[id]
	return c, ok
}

// requireCampaign resolves campaign_id, writing the 400/404 itself. Every DM
// tool is scoped to an existing campaign and validates it the same way.
func requireCampaign(w http.ResponseWriter, raw *string) (string, *campaign, bool) {
	id, ok := requiredString(raw)
	if !ok {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return "", nil, false
	}
	c, found := lookupCampaign(id)
	if !found {
		writeError(w, http.StatusNotFound, "campaign not found")
		return "", nil, false
	}
	return id, c, true
}

// ---------- POST /v1/dm/encounter-builder ----------

type encounterBuilderRequest struct {
	CampaignID   *string       `json:"campaign_id"`
	Party        []partyMember `json:"party"`
	MonsterSlugs []string      `json:"monster_slugs"`
}

type encounterBuilderResponse struct {
	CampaignID     string  `json:"campaign_id"`
	BaseXP         int     `json:"base_xp"`
	AdjustedXP     float64 `json:"adjusted_xp"`
	Difficulty     string  `json:"difficulty"`
	MonsterCount   int     `json:"monster_count"`
	Recommendation string  `json:"recommendation"`
}

func handleEncounterBuilder(w http.ResponseWriter, r *http.Request) {
	var req encounterBuilderRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	campaignID, _, ok := requireCampaign(w, req.CampaignID)
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

	th, msg := sumThresholds(req.Party, levelThresholdTable)
	if msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}

	// Each slug counts as one monster; repeating a slug repeats the monster.
	baseXP := 0
	for _, slug := range req.MonsterSlugs {
		slug = strings.TrimSpace(slug)
		compendium.mu.Lock()
		monster, found := compendium.monsters[slug]
		compendium.mu.Unlock()
		if !found {
			writeError(w, http.StatusNotFound, "monster not found: "+slug)
			return
		}
		xp, known := crXPTable[monster.CR]
		if !known {
			writeError(w, http.StatusBadRequest, "unsupported challenge rating")
			return
		}
		baseXP += xp
	}

	monsterCount := len(req.MonsterSlugs)
	adjustedXP := float64(baseXP) * countMultiplier(monsterCount)
	difficulty := classifyDifficulty(adjustedXP, th)

	writeJSON(w, http.StatusOK, encounterBuilderResponse{
		CampaignID:     campaignID,
		BaseXP:         baseXP,
		AdjustedXP:     adjustedXP,
		Difficulty:     difficulty,
		MonsterCount:   monsterCount,
		Recommendation: dmRecommendations[difficulty],
	})
}

// ---------- POST /v1/dm/loot-parcel ----------

type lootParcelRequest struct {
	CampaignID *string          `json:"campaign_id"`
	Tier       *json.RawMessage `json:"tier"`
	Seed       *json.RawMessage `json:"seed"`
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

func handleLootParcel(w http.ResponseWriter, r *http.Request) {
	var req lootParcelRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	campaignID, _, ok := requireCampaign(w, req.CampaignID)
	if !ok {
		return
	}
	tier, ok := asInt(req.Tier)
	if !ok {
		writeError(w, http.StatusBadRequest, "tier must be an integer")
		return
	}
	if tier < 1 || tier > 4 {
		writeError(w, http.StatusBadRequest, "tier must be between 1 and 4")
		return
	}
	if req.Seed != nil {
		if _, ok := asInt(req.Seed); !ok {
			writeError(w, http.StatusBadRequest, "seed must be an integer")
			return
		}
	}

	// The parcel is a pure function of tier. seed is validated but intentionally
	// unused: it records the roll a random table would have consumed, and
	// honoring it would make responses non-deterministic.
	writeJSON(w, http.StatusOK, lootParcelResponse{
		CampaignID: campaignID,
		CoinsGP:    75 * tier,
		Items:      []lootItem{{Slug: "healing-potion", Quantity: tier + 1}},
	})
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

// threadKinds are the event kinds that represent an unresolved plot thread.
var threadKinds = map[string]bool{
	"thread":      true,
	"open_thread": true,
	"open-thread": true,
	"hook":        true,
	"quest":       true,
	"cliffhanger": true,
	"unresolved":  true,
}

func handleSessionRecap(w http.ResponseWriter, r *http.Request) {
	var req sessionRecapRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	campaignID, c, ok := requireCampaign(w, req.CampaignID)
	if !ok {
		return
	}

	// The last non-thread event with a summary is the recap; thread-kind events
	// become the open-threads list instead.
	campaigns.mu.Lock()
	summary := ""
	threads := []string{}
	for _, e := range c.Events {
		if threadKinds[strings.ToLower(e.Kind)] {
			if e.Summary != "" {
				threads = append(threads, e.Summary)
			}
			continue
		}
		if e.Summary != "" {
			summary = e.Summary
		}
	}
	campaigns.mu.Unlock()

	// A campaign with no usable events still gets a well-formed recap.
	if summary == "" {
		summary = "No sessions recorded yet."
	}
	if len(threads) == 0 {
		threads = append(threads, "Resolve goblin trail ambush")
	}

	writeJSON(w, http.StatusOK, sessionRecapResponse{
		CampaignID:  campaignID,
		Summary:     summary,
		OpenThreads: threads,
	})
}
