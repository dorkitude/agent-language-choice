package main

import (
	"fmt"
	"net/http"
	"sync"
)

// rngRoll is one immutable campaign RNG ledger entry.
type rngRoll struct {
	CampaignID string
	Sequence   int
	RollID     string
	Sides      int
	Result     int
}

// rngLedger is a campaign's deterministic RNG seed plus its ordered,
// immutable roll ledger.
type rngLedger struct {
	CampaignID string
	Seed       string
	Rolls      []*rngRoll
}

// rngLedgersMu guards rngLedgers, the in-memory index mirroring the
// play_rng_seeds/play_rng_rolls tables. Keyed by campaign id.
var (
	rngLedgersMu sync.Mutex
	rngLedgers   = map[string]*rngLedger{}
)

func rngRollJSON(roll *rngRoll) map[string]any {
	return map[string]any{
		"roll_id":  roll.RollID,
		"sides":    roll.Sides,
		"result":   roll.Result,
		"sequence": roll.Sequence,
	}
}

func rngLedgerJSON(l *rngLedger) map[string]any {
	rolls := make([]map[string]any, 0, len(l.Rolls))
	for _, roll := range l.Rolls {
		rolls = append(rolls, rngRollJSON(roll))
	}
	return map[string]any{
		"seed":  l.Seed,
		"rolls": rolls,
	}
}

// rngRollResult computes the stable, deterministic roll outcome for the
// given seed, append-order sequence, roll id, and number of sides.
func rngRollResult(seed string, sequence int, rollID string, sides int) int {
	data := fmt.Sprintf("%s|%d|%s|%d", seed, sequence, rollID, sides)
	var acc uint32
	for i := 0; i < len(data); i++ {
		acc = acc*31 + uint32(data[i])
	}
	return int(acc%uint32(sides)) + 1
}

func requireRngMember(w http.ResponseWriter, actor *user, c *playCampaign, campaignID string) bool {
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be a campaign member to access the rng ledger")
		return false
	}
	return true
}

type configureRngSeedRequest struct {
	Seed string `json:"seed"`
}

// configureRngSeedHandler lets the campaign dm set the campaign's
// deterministic RNG seed exactly once. Replacing an already configured seed
// returns 409 without mutating the ledger.
func configureRngSeedHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req configureRngSeedRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may configure the rng seed")
		return
	}

	if req.Seed == "" {
		writeError(w, http.StatusBadRequest, "seed must be a nonempty string")
		return
	}

	rngLedgersMu.Lock()
	defer rngLedgersMu.Unlock()

	if _, exists := rngLedgers[campaignID]; exists {
		writeError(w, http.StatusConflict, "rng seed is already configured for this campaign")
		return
	}

	l := &rngLedger{
		CampaignID: campaignID,
		Seed:       req.Seed,
		Rolls:      []*rngRoll{},
	}
	if err := saveRngSeedToDB(l); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save rng seed")
		return
	}
	rngLedgers[campaignID] = l

	writeJSON(w, http.StatusOK, rngLedgerJSON(l))
}

type appendRngRollRequest struct {
	RollID string `json:"roll_id"`
	Sides  int    `json:"sides"`
}

// appendRngRollHandler lets authenticated campaign members, including the
// dm, append a deterministic roll to the campaign's RNG ledger.
func appendRngRollHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req appendRngRollRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !requireRngMember(w, actor, c, campaignID) {
		return
	}

	rngLedgersMu.Lock()
	defer rngLedgersMu.Unlock()

	l, exists := rngLedgers[campaignID]
	if !exists {
		writeError(w, http.StatusConflict, "rng seed must be configured before rolling")
		return
	}

	if req.RollID == "" {
		writeError(w, http.StatusBadRequest, "roll_id must be a nonempty string")
		return
	}
	if req.Sides < 2 || req.Sides > 100 {
		writeError(w, http.StatusBadRequest, "sides must be an integer from 2 through 100")
		return
	}

	for _, existing := range l.Rolls {
		if existing.RollID == req.RollID {
			writeError(w, http.StatusConflict, "roll_id already exists in this campaign rng ledger")
			return
		}
	}

	sequence := len(l.Rolls) + 1
	result := rngRollResult(l.Seed, sequence, req.RollID, req.Sides)

	roll := &rngRoll{
		CampaignID: campaignID,
		Sequence:   sequence,
		RollID:     req.RollID,
		Sides:      req.Sides,
		Result:     result,
	}
	if err := saveRngRollToDB(roll); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save rng roll")
		return
	}
	l.Rolls = append(l.Rolls, roll)

	writeJSON(w, http.StatusCreated, rngRollJSON(roll))
}

// getRngLedgerHandler lets authenticated campaign members, including the
// dm, read the campaign's exact seed plus ordered immutable roll ledger.
func getRngLedgerHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !requireRngMember(w, actor, c, campaignID) {
		return
	}

	rngLedgersMu.Lock()
	defer rngLedgersMu.Unlock()

	l, exists := rngLedgers[campaignID]
	if !exists {
		l = &rngLedger{CampaignID: campaignID, Seed: "", Rolls: []*rngRoll{}}
	}

	writeJSON(w, http.StatusOK, rngLedgerJSON(l))
}
