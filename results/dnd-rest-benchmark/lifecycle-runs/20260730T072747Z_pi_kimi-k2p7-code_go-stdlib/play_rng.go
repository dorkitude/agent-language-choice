package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// configureRNGSeedRequest binds the payload for configuring a campaign RNG seed.
type configureRNGSeedRequest struct {
	Seed string `json:"seed"`
}

// rngRollResponse is the immutable ledger record returned by a successful roll
// append. The field order matches the stage contract.
type rngRollResponse struct {
	RollID   string `json:"roll_id"`
	Sides    int    `json:"sides"`
	Result   int    `json:"result"`
	Sequence int    `json:"sequence"`
}

// rngSeedResponse is the seed configuration read model. It is also used for
// the successful PUT response so the ledger is returned empty.
type rngSeedResponse struct {
	Seed  string            `json:"seed"`
	Rolls []rngRollResponse `json:"rolls"`
}

// rngLedgerResponse is the campaign RNG ledger read model.
type rngLedgerResponse struct {
	Seed  string            `json:"seed"`
	Rolls []rngRollResponse `json:"rolls"`
}

// deterministicRoll computes the campaign-scoped deterministic roll result.
// It uses the exact byte string seed + "|" + decimal(sequence) + "|" +
// roll_id + "|" + decimal(sides) and an unsigned 32-bit accumulator with
// multiplier 31. The result is ((acc mod 2^32) mod sides) + 1.
func deterministicRoll(seed string, sequence int, rollID string, sides int) int {
	input := fmt.Sprintf("%s|%d|%s|%d", seed, sequence, rollID, sides)
	var acc uint32
	for _, b := range []byte(input) {
		acc = (acc * 31) + uint32(b)
	}
	return int((acc % uint32(sides)) + 1)
}

// queryRNGSeed loads the configured seed for a campaign, if any. The caller
// must hold dbMu.
func queryRNGSeed(campaignID string) (string, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT seed FROM campaign_rng_seeds WHERE campaign_id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		return "", false, err
	}
	var rows []struct {
		Seed string `json:"seed"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return "", false, err
	}
	if len(rows) == 0 {
		return "", false, nil
	}
	return rows[0].Seed, true, nil
}

// queryRNGRolls loads all immutable roll records for a campaign ordered by
// sequence. The caller must hold dbMu.
func queryRNGRolls(campaignID string) ([]rngRollResponse, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT sequence, roll_id, sides, result FROM campaign_rng_rolls WHERE campaign_id=%s ORDER BY sequence;", sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var rows []struct {
		Sequence int    `json:"sequence"`
		RollID   string `json:"roll_id"`
		Sides    int    `json:"sides"`
		Result   int    `json:"result"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	rolls := make([]rngRollResponse, 0, len(rows))
	for _, r := range rows {
		rolls = append(rolls, rngRollResponse{
			RollID:   r.RollID,
			Sides:    r.Sides,
			Result:   r.Result,
			Sequence: r.Sequence,
		})
	}
	return rolls, nil
}

// nextRNGRollSequence returns the next monotonic append-order sequence for a
// campaign RNG ledger. The caller must hold dbMu.
func nextRNGRollSequence(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_rng_rolls WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextSeq, nil
}

// configureRNGSeedHandler lets the campaign owner (DM) configure the campaign
// RNG seed. The seed must be a nonempty string, and replacing an already
// configured seed returns 409 without mutating the ledger.
func configureRNGSeedHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req configureRNGSeedRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Seed == "" {
		writeError(w, http.StatusBadRequest, "invalid seed")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_rng_seeds WHERE campaign_id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		log.Printf("rng seed exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "seed already configured")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_rng_seeds (campaign_id, seed) VALUES (%s, %s);",
		sq(campaignID), sq(req.Seed))); err != nil {
		log.Printf("rng seed insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, rngSeedResponse{
		Seed:  req.Seed,
		Rolls: []rngRollResponse{},
	})
}

// appendRNGRollHandler lets authenticated campaign members (including the DM)
// append a deterministic roll to the campaign ledger. A configured seed is
// required; roll_id must be unique within the campaign; sides must be an
// integer from 2 through 100 inclusive.
func appendRNGRollHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
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
		writeError(w, http.StatusBadRequest, "invalid roll")
		return
	}
	if req.Sides < 2 || req.Sides > 100 {
		writeError(w, http.StatusBadRequest, "invalid sides")
		return
	}

	seed, hasSeed, err := queryRNGSeed(campaignID)
	if err != nil {
		log.Printf("rng roll seed query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !hasSeed {
		writeError(w, http.StatusConflict, "seed not configured")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_rng_rolls WHERE campaign_id=%s AND roll_id=%s LIMIT 1;", sq(campaignID), sq(req.RollID)))
	if err != nil {
		log.Printf("rng roll duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "roll_id already exists")
		return
	}

	sequence, err := nextRNGRollSequence(campaignID)
	if err != nil {
		log.Printf("rng roll sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	result := deterministicRoll(seed, sequence, req.RollID, req.Sides)

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_rng_rolls (campaign_id, sequence, roll_id, sides, result) VALUES (%s, %d, %s, %d, %d);",
		sq(campaignID), sequence, sq(req.RollID), req.Sides, result)); err != nil {
		log.Printf("rng roll insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, rngRollResponse{
		RollID:   req.RollID,
		Sides:    req.Sides,
		Result:   result,
		Sequence: sequence,
	})
}

// getRNGLedgerHandler lets authenticated campaign members (including the DM)
// read the configured seed and the ordered immutable roll records.
func getRNGLedgerHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	seed, _, err := queryRNGSeed(campaignID)
	if err != nil {
		log.Printf("rng ledger seed query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	rolls, err := queryRNGRolls(campaignID)
	if err != nil {
		log.Printf("rng ledger rolls query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, rngLedgerResponse{
		Seed:  seed,
		Rolls: rolls,
	})
}
