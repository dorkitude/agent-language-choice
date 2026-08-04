package main

import (
	"net/http"
	"sync"
)

// playRelationship is a directed edge between two campaign entities (member
// character ids or NPC ids), keyed by (source_id, target_id, kind).
type playRelationship struct {
	CampaignID string `json:"-"`
	SourceID   string `json:"source_id"`
	TargetID   string `json:"target_id"`
	Kind       string `json:"kind"`
	Score      int    `json:"score"`
}

// campaignRelationshipsMu guards campaignRelationships, the in-memory index
// mirroring the play_relationships table. Keyed by campaign id, holding
// edges in insertion order.
var (
	campaignRelationshipsMu sync.Mutex
	campaignRelationships   = map[string][]*playRelationship{}
)

// isCampaignEntity reports whether id names an existing campaign entity: a
// campaign member's character id or an NPC id. Callers must not already hold
// playMembersMu or campaignNPCsMu.
func isCampaignEntity(campaignID, id string) bool {
	playMembersMu.Lock()
	for _, m := range playMembers[campaignID] {
		if m.CharacterID == id {
			playMembersMu.Unlock()
			return true
		}
	}
	playMembersMu.Unlock()

	campaignNPCsMu.Lock()
	defer campaignNPCsMu.Unlock()
	_, exists := campaignNPCs[campaignID][id]
	return exists
}

func relationshipJSON(rel *playRelationship) map[string]any {
	return map[string]any{
		"source_id": rel.SourceID,
		"target_id": rel.TargetID,
		"kind":      rel.Kind,
		"score":     rel.Score,
	}
}

type createRelationshipRequest struct {
	SourceID string `json:"source_id"`
	TargetID string `json:"target_id"`
	Kind     string `json:"kind"`
	Score    *int   `json:"score"`
}

// createRelationshipHandler lets the campaign's owning dm create a directed
// relationship edge between two campaign entities.
func createRelationshipHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createRelationshipRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create relationships")
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
	if *req.Score < -100 || *req.Score > 100 {
		writeError(w, http.StatusBadRequest, "score must be an integer from -100 through 100")
		return
	}

	if !isCampaignEntity(campaignID, req.SourceID) || !isCampaignEntity(campaignID, req.TargetID) {
		writeError(w, http.StatusNotFound, "source_id and target_id must name existing campaign entities")
		return
	}

	campaignRelationshipsMu.Lock()
	defer campaignRelationshipsMu.Unlock()

	for _, rel := range campaignRelationships[campaignID] {
		if rel.SourceID == req.SourceID && rel.TargetID == req.TargetID && rel.Kind == req.Kind {
			writeError(w, http.StatusConflict, "relationship edge already exists")
			return
		}
	}

	rel := &playRelationship{
		CampaignID: campaignID,
		SourceID:   req.SourceID,
		TargetID:   req.TargetID,
		Kind:       req.Kind,
		Score:      *req.Score,
	}
	if err := saveRelationshipToDB(rel); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save relationship")
		return
	}
	campaignRelationships[campaignID] = append(campaignRelationships[campaignID], rel)

	writeJSON(w, http.StatusCreated, relationshipJSON(rel))
}

type updateRelationshipRequest struct {
	Score *int `json:"score"`
}

// updateRelationshipHandler lets the campaign's owning dm update the score of
// an existing relationship edge.
func updateRelationshipHandler(w http.ResponseWriter, r *http.Request, campaignID, sourceID, targetID, kind string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req updateRelationshipRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may update relationships")
		return
	}

	if req.Score == nil || *req.Score < -100 || *req.Score > 100 {
		writeError(w, http.StatusBadRequest, "score must be an integer from -100 through 100")
		return
	}

	campaignRelationshipsMu.Lock()
	defer campaignRelationshipsMu.Unlock()

	var rel *playRelationship
	for _, e := range campaignRelationships[campaignID] {
		if e.SourceID == sourceID && e.TargetID == targetID && e.Kind == kind {
			rel = e
			break
		}
	}
	if rel == nil {
		writeError(w, http.StatusNotFound, "relationship edge not found")
		return
	}

	rel.Score = *req.Score
	if err := saveRelationshipToDB(rel); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save relationship")
		return
	}

	writeJSON(w, http.StatusOK, relationshipJSON(rel))
}

// listRelationshipsHandler returns all relationship edges for a campaign in
// insertion order. Any authenticated campaign member (including the dm) may
// call this.
func listRelationshipsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	isDM := actor.Username == c.Owner
	if !isDM && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	campaignRelationshipsMu.Lock()
	defer campaignRelationshipsMu.Unlock()

	edges := make([]map[string]any, 0, len(campaignRelationships[campaignID]))
	for _, rel := range campaignRelationships[campaignID] {
		edges = append(edges, relationshipJSON(rel))
	}

	writeJSON(w, http.StatusOK, map[string]any{"edges": edges})
}
