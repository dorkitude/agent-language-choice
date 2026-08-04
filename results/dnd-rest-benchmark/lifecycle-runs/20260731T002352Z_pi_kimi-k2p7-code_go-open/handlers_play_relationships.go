package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createPlayRelationshipHandler creates a directed relationship edge between
// two campaign entities. Only the campaign owner (DM) may create edges. The
// source and target must be existing campaign member character ids or NPC ids,
// must differ, kind must be nonempty, and score must be an integer in
// [-100, 100]. Duplicate (source_id, target_id, kind) edges return 409.
func createPlayRelationshipHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create relationships")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create relationships")
		return
	}

	var req relationshipCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.SourceID) == "" {
		badRequest(w, "source_id is required")
		return
	}
	if strings.TrimSpace(req.TargetID) == "" {
		badRequest(w, "target_id is required")
		return
	}
	if strings.TrimSpace(req.Kind) == "" {
		badRequest(w, "kind is required")
		return
	}
	if req.Score == nil {
		badRequest(w, "score is required")
		return
	}
	if *req.Score < -100 || *req.Score > 100 {
		badRequest(w, "score must be between -100 and 100")
		return
	}
	if req.SourceID == req.TargetID {
		badRequest(w, "source_id and target_id must differ")
		return
	}

	sourceExists, err := dbPlayEntityExists(id, req.SourceID)
	if err != nil {
		log.Printf("check source entity: %v", err)
		badRequest(w, "failed to validate relationship")
		return
	}
	if !sourceExists {
		notFound(w, "source entity not found")
		return
	}

	targetExists, err := dbPlayEntityExists(id, req.TargetID)
	if err != nil {
		log.Printf("check target entity: %v", err)
		badRequest(w, "failed to validate relationship")
		return
	}
	if !targetExists {
		notFound(w, "target entity not found")
		return
	}

	if err := dbCreatePlayRelationship(id, req.SourceID, req.TargetID, req.Kind, *req.Score); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "relationship already exists")
			return
		}
		log.Printf("create play relationship: %v", err)
		badRequest(w, "failed to create relationship")
		return
	}

	writeJSON(w, http.StatusCreated, playRelationship{
		SourceID: req.SourceID,
		TargetID: req.TargetID,
		Kind:     req.Kind,
		Score:    *req.Score,
	})
}

// updatePlayRelationshipHandler updates the score of an existing directed
// relationship edge. Only the campaign owner (DM) may update edges. The
// addressed edge must exist, otherwise 404. The score must be an integer in
// [-100, 100].
func updatePlayRelationshipHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can update relationships")
		return
	}

	id := r.PathValue("id")
	sourceID := r.PathValue("source_id")
	targetID := r.PathValue("target_id")
	kind := r.PathValue("kind")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can update relationships")
		return
	}

	var req relationshipUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Score == nil {
		badRequest(w, "score is required")
		return
	}
	if *req.Score < -100 || *req.Score > 100 {
		badRequest(w, "score must be between -100 and 100")
		return
	}

	rel, err := dbUpdatePlayRelationshipScore(id, sourceID, targetID, kind, *req.Score)
	if err != nil {
		log.Printf("update play relationship: %v", err)
		badRequest(w, "failed to update relationship")
		return
	}
	if rel == nil {
		notFound(w, "relationship not found")
		return
	}

	writeJSON(w, http.StatusOK, rel)
}

// getPlayRelationshipsHandler lists all relationship edges in a campaign in
// insertion order. Available to any authenticated campaign member.
func getPlayRelationshipsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	edges, err := dbGetPlayRelationships(id)
	if err != nil {
		log.Printf("get play relationships: %v", err)
		badRequest(w, "failed to read relationships")
		return
	}

	writeJSON(w, http.StatusOK, relationshipsResponse{Edges: edges})
}
