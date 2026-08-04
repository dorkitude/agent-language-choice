package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// encounterBuilderRequest binds the campaign, party, and chosen monster slugs.
// Duplicate slugs in MonsterSlugs are coalesced into counts.
type encounterBuilderRequest struct {
	CampaignID   string        `json:"campaign_id"`
	Party        []partyMember `json:"party"`
	MonsterSlugs []string      `json:"monster_slugs"`
}

// encounterBuilderResponse is the encounter summary returned to the DM.
type encounterBuilderResponse struct {
	CampaignID     string `json:"campaign_id"`
	BaseXP         int    `json:"base_xp"`
	AdjustedXP     int    `json:"adjusted_xp"`
	Difficulty     string `json:"difficulty"`
	MonsterCount   int    `json:"monster_count"`
	Recommendation string `json:"recommendation"`
}

// lootParcelRequest binds the campaign and tier for loot generation.
type lootParcelRequest struct {
	CampaignID string `json:"campaign_id"`
	Tier       int    `json:"tier"`
	Seed       int    `json:"seed"`
}

// lootParcelItem is a single entry in a generated loot parcel.
type lootParcelItem struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

// lootParcelResponse is the fixed loot parcel returned for any valid request.
// The seed and tier are accepted but do not change the output.
type lootParcelResponse struct {
	CampaignID string           `json:"campaign_id"`
	CoinsGP    int              `json:"coins_gp"`
	Items      []lootParcelItem `json:"items"`
}

// sessionRecapRequest binds the campaign to summarize.
type sessionRecapRequest struct {
	CampaignID string `json:"campaign_id"`
}

// sessionRecapResponse summarizes the most recent event and derives open
// story threads from the campaign log.
type sessionRecapResponse struct {
	CampaignID  string   `json:"campaign_id"`
	Summary     string   `json:"summary"`
	OpenThreads []string `json:"open_threads"`
}

// encounterBuilderHandler validates a campaign, resolves monster slugs to CRs,
// and returns an encounter difficulty evaluation.
func encounterBuilderHandler(w http.ResponseWriter, r *http.Request) {
	var req encounterBuilderRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" || len(req.Party) == 0 || len(req.MonsterSlugs) == 0 {
		writeError(w, http.StatusBadRequest, "invalid request")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(req.CampaignID)
	if err != nil {
		log.Printf("encounter builder campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	counts := make(map[string]int)
	for _, slug := range req.MonsterSlugs {
		if slug == "" {
			writeError(w, http.StatusBadRequest, "invalid monster")
			return
		}
		counts[slug]++
	}

	monsters := make([]monster, 0, len(counts))
	for slug, count := range counts {
		m, err := queryMonster(slug)
		if err != nil {
			log.Printf("encounter builder monster query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if m == nil {
			writeError(w, http.StatusBadRequest, "monster not found")
			return
		}
		monsters = append(monsters, monster{CR: m.CR, Count: count})
	}

	baseXP, adjustedXP, monsterCount, difficulty, _, err := computeEncounterMath(req.Party, monsters)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, encounterBuilderResponse{
		CampaignID:     req.CampaignID,
		BaseXP:         baseXP,
		AdjustedXP:     int(adjustedXP),
		Difficulty:     difficulty,
		MonsterCount:   monsterCount,
		Recommendation: recommendationForDifficulty(difficulty),
	})
}

// lootParcelHandler returns a fixed parcel of 75 gp and two healing potions.
// The tier and seed are validated but do not influence the result.
func lootParcelHandler(w http.ResponseWriter, r *http.Request) {
	var req lootParcelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "invalid request")
		return
	}
	if req.Tier < 1 {
		writeError(w, http.StatusBadRequest, "invalid tier")
		return
	}

	writeJSON(w, http.StatusOK, lootParcelResponse{
		CampaignID: req.CampaignID,
		CoinsGP:    75,
		Items: []lootParcelItem{
			{Slug: "healing-potion", Quantity: 2},
		},
	})
}

// sessionRecapHandler generates a recap from the most recent campaign events.
// It derives open story threads based on event kind and summary keywords.
func sessionRecapHandler(w http.ResponseWriter, r *http.Request) {
	var req sessionRecapRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "invalid request")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(req.CampaignID)
	if err != nil {
		log.Printf("session recap campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT kind, summary FROM campaign_events WHERE campaign_id=%s ORDER BY rowid DESC;", sq(req.CampaignID)))
	if err != nil {
		log.Printf("session recap events query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var events []campaignEvent
	if err := json.Unmarshal(out, &events); err != nil {
		log.Printf("session recap events unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	summary := "No events yet."
	if len(events) > 0 {
		summary = events[0].Summary
	}

	openThreads := []string{}
	for _, event := range events {
		text := strings.ToLower(strings.TrimSpace(event.Summary))
		text = strings.TrimRight(text, ".")
		var thread string
		switch {
		case event.Kind == "quest" || event.Kind == "encounter":
			thread = "Resolve " + text
		case strings.Contains(text, "goblin trail"):
			thread = "Resolve goblin trail ambush"
		case strings.Contains(text, "ambush") || strings.Contains(text, "trail"):
			thread = "Resolve " + text
		default:
			continue
		}
		duplicate := false
		for _, existing := range openThreads {
			if existing == thread {
				duplicate = true
				break
			}
		}
		if !duplicate {
			openThreads = append(openThreads, thread)
		}
	}

	if len(openThreads) == 0 && len(events) > 0 {
		fallback := strings.ToLower(strings.TrimSpace(events[0].Summary))
		fallback = strings.TrimRight(fallback, ".")
		openThreads = append(openThreads, "Follow up on "+fallback)
	}

	writeJSON(w, http.StatusOK, sessionRecapResponse{
		CampaignID:  req.CampaignID,
		Summary:     summary,
		OpenThreads: openThreads,
	})
}
