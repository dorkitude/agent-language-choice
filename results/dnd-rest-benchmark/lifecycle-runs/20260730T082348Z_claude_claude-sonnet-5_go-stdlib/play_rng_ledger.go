package main

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// playRngRoll is an immutable campaign-scoped RNG ledger record.
type playRngRoll struct {
	RollID   string
	Sides    int
	Result   int
	Sequence int
}

func playRngRollResponse(roll *playRngRoll) map[string]interface{} {
	return map[string]interface{}{
		"roll_id":  roll.RollID,
		"sides":    roll.Sides,
		"result":   roll.Result,
		"sequence": roll.Sequence,
	}
}

func playRngLedgerState(c *playCampaign) map[string]interface{} {
	rolls := make([]map[string]interface{}, 0, len(c.RngRolls))
	for _, roll := range c.RngRolls {
		rolls = append(rolls, playRngRollResponse(roll))
	}
	return map[string]interface{}{
		"seed":  c.RngSeed,
		"rolls": rolls,
	}
}

// playStableRoll computes the stable RNG ledger roll outcome for the given
// seed, sequence, roll id, and sides, per the fixed accumulator algorithm.
func playStableRoll(seed string, sequence int, rollID string, sides int) int {
	data := fmt.Sprintf("%s|%d|%s|%d", seed, sequence, rollID, sides)
	var acc uint32
	for i := 0; i < len(data); i++ {
		acc = acc*31 + uint32(data[i])
	}
	return int(acc%uint32(sides)) + 1
}

// handlePlayCampaignRngLedgerSub routes the "rng-seed", "rng-rolls", and
// "rng-ledger" sub-paths of a play campaign. It returns false if rest does
// not name an rng ledger path, so the caller can fall through to its own
// routing.
func handlePlayCampaignRngLedgerSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	switch rest {
	case "rng-seed":
		if r.Method != http.MethodPut {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleConfigurePlayRngSeed(w, r, campaignID)
		return true
	case "rng-rolls":
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleAppendPlayRngRoll(w, r, campaignID)
		return true
	case "rng-ledger":
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleReadPlayRngLedger(w, r, campaignID)
		return true
	}
	return false
}

func handleConfigurePlayRngSeed(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Seed string `json:"seed"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Seed == "" {
		writeError(w, http.StatusBadRequest, "seed is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be the campaign dm")
		return
	}
	if c.RngSeedSet {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "rng seed already configured")
		return
	}

	c.RngSeed = req.Seed
	c.RngSeedSet = true
	resp := playRngLedgerState(c)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

func handleAppendPlayRngRoll(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		RollID string `json:"roll_id"`
		Sides  int    `json:"sides"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.RollID == "" {
		writeError(w, http.StatusBadRequest, "roll_id is required")
		return
	}
	if req.Sides < 2 || req.Sides > 100 {
		writeError(w, http.StatusBadRequest, "sides must be an integer from 2 through 100")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username && !playIsCampaignMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign dm or member")
		return
	}
	if !c.RngSeedSet {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "rng seed not configured")
		return
	}
	if c.RngRollIDs != nil && c.RngRollIDs[req.RollID] {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "roll_id already used in this campaign")
		return
	}

	c.RngRollSeq++
	result := playStableRoll(c.RngSeed, c.RngRollSeq, req.RollID, req.Sides)
	entry := &playRngRoll{
		RollID:   req.RollID,
		Sides:    req.Sides,
		Result:   result,
		Sequence: c.RngRollSeq,
	}
	c.RngRolls = append(c.RngRolls, entry)
	if c.RngRollIDs == nil {
		c.RngRollIDs = make(map[string]bool)
	}
	c.RngRollIDs[req.RollID] = true
	resp := playRngRollResponse(entry)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

func handleReadPlayRngLedger(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username && !playIsCampaignMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign dm or member")
		return
	}

	resp := playRngLedgerState(c)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}
