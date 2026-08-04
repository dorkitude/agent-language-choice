package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playRelationship is a directed relationship edge between two campaign
// entities (campaign member character ids or npc ids).
type playRelationship struct {
	SourceID string
	TargetID string
	Kind     string
	Score    int
}

func playRelationshipResponse(rel *playRelationship) map[string]interface{} {
	return map[string]interface{}{
		"source_id": rel.SourceID,
		"target_id": rel.TargetID,
		"kind":      rel.Kind,
		"score":     rel.Score,
	}
}

// isPlayCampaignEntity reports whether id names an existing campaign entity:
// a member's character id or an npc id.
func isPlayCampaignEntity(c *playCampaign, id string) bool {
	for _, m := range c.Members {
		if m.CharacterID == id {
			return true
		}
	}
	if c.NPCs != nil {
		if _, ok := c.NPCs[id]; ok {
			return true
		}
	}
	return false
}

// handlePlayCampaignRelationshipSub routes the "relationships" and
// "relationships/..." sub-paths of a play campaign. It returns false if rest
// does not name a relationships path, so the caller can fall through to its
// own routing.
func handlePlayCampaignRelationshipSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "relationships" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayRelationship(w, r, campaignID)
		case http.MethodGet:
			handleListPlayRelationships(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if !strings.HasPrefix(rest, "relationships/") {
		return false
	}
	relRest := strings.TrimPrefix(rest, "relationships/")
	parts := strings.SplitN(relRest, "/", 3)
	if len(parts) != 3 || parts[0] == "" || parts[1] == "" || parts[2] == "" {
		return false
	}
	if r.Method != http.MethodPut {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return true
	}
	handleUpdatePlayRelationship(w, r, campaignID, parts[0], parts[1], parts[2])
	return true
}

// handleCreatePlayRelationship lets the campaign dm create a new directed
// relationship edge between two campaign entities.
func handleCreatePlayRelationship(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		SourceID string   `json:"source_id"`
		TargetID string   `json:"target_id"`
		Kind     string   `json:"kind"`
		Score    *float64 `json:"score"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SourceID == "" || req.TargetID == "" || req.Kind == "" || req.Score == nil {
		writeError(w, http.StatusBadRequest, "source_id, target_id, kind, and score are required")
		return
	}
	if req.SourceID == req.TargetID {
		writeError(w, http.StatusBadRequest, "source_id and target_id must differ")
		return
	}
	score := *req.Score
	if score != float64(int(score)) || score < -100 || score > 100 {
		writeError(w, http.StatusBadRequest, "score must be an integer from -100 through 100")
		return
	}
	scoreInt := int(score)

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create relationship edges")
		return
	}
	if !isPlayCampaignEntity(c, req.SourceID) || !isPlayCampaignEntity(c, req.TargetID) {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "unknown campaign entity")
		return
	}
	for _, rel := range c.Relationships {
		if rel.SourceID == req.SourceID && rel.TargetID == req.TargetID && rel.Kind == req.Kind {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "relationship edge already exists")
			return
		}
	}

	rel := &playRelationship{
		SourceID: req.SourceID,
		TargetID: req.TargetID,
		Kind:     req.Kind,
		Score:    scoreInt,
	}
	c.Relationships = append(c.Relationships, rel)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playRelationshipResponse(rel))
}

// handleUpdatePlayRelationship lets the campaign dm update the score of an
// existing relationship edge.
func handleUpdatePlayRelationship(w http.ResponseWriter, r *http.Request, campaignID, sourceID, targetID, kind string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Score *float64 `json:"score"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Score == nil {
		writeError(w, http.StatusBadRequest, "score is required")
		return
	}
	score := *req.Score
	if score != float64(int(score)) || score < -100 || score > 100 {
		writeError(w, http.StatusBadRequest, "score must be an integer from -100 through 100")
		return
	}
	scoreInt := int(score)

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may update relationship edges")
		return
	}
	var rel *playRelationship
	for _, candidate := range c.Relationships {
		if candidate.SourceID == sourceID && candidate.TargetID == targetID && candidate.Kind == kind {
			rel = candidate
			break
		}
	}
	if rel == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "relationship edge not found")
		return
	}

	rel.Score = scoreInt
	resp := playRelationshipResponse(rel)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handleListPlayRelationships returns all relationship edges for a campaign
// in insertion order. Any authenticated campaign member may call this.
func handleListPlayRelationships(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view relationships")
		return
	}
	edges := make([]map[string]interface{}, 0, len(c.Relationships))
	for _, rel := range c.Relationships {
		edges = append(edges, playRelationshipResponse(rel))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"edges": edges,
	})
}
