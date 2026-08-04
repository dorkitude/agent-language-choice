package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// relationship is the full directed relationship edge shape.
type relationship struct {
	SourceID string `json:"source_id"`
	TargetID string `json:"target_id"`
	Kind     string `json:"kind"`
	Score    int    `json:"score"`
}

// relationshipListResponse is the shape returned by the relationship list endpoint.
type relationshipListResponse struct {
	Edges []relationship `json:"edges"`
}

// createRelationshipRequest binds the payload for creating a new relationship edge.
type createRelationshipRequest struct {
	SourceID string `json:"source_id"`
	TargetID string `json:"target_id"`
	Kind     string `json:"kind"`
	Score    *int   `json:"score"`
}

// updateRelationshipRequest binds the payload for updating a relationship edge score.
type updateRelationshipRequest struct {
	Score *int `json:"score"`
}

// campaignEntityExists reports whether the given entity id names an existing
// campaign member character or an existing campaign NPC for the campaign.
// The caller must hold dbMu.
func campaignEntityExists(campaignID, entityID string) (bool, error) {
	memberExists, err := queryExists(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND character_id=%s LIMIT 1;", sq(campaignID), sq(entityID)))
	if err != nil {
		return false, err
	}
	if memberExists {
		return true, nil
	}
	return queryExists(fmt.Sprintf("SELECT 1 FROM campaign_npcs WHERE campaign_id=%s AND npc_id=%s LIMIT 1;", sq(campaignID), sq(entityID)))
}

// queryRelationship loads a single relationship edge by its natural key.
// The caller must hold dbMu.
func queryRelationship(campaignID, sourceID, targetID, kind string) (*relationship, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT source_id, target_id, kind, score FROM campaign_relationships WHERE campaign_id=%s AND source_id=%s AND target_id=%s AND kind=%s LIMIT 1;",
		sq(campaignID), sq(sourceID), sq(targetID), sq(kind)))
	if err != nil {
		return nil, false, err
	}
	var rows []relationship
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// queryRelationships loads all relationship edges for a campaign in insertion order.
// The caller must hold dbMu.
func queryRelationships(campaignID string) ([]relationship, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT source_id, target_id, kind, score FROM campaign_relationships WHERE campaign_id=%s ORDER BY id;", sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var edges []relationship
	if err := json.Unmarshal(out, &edges); err != nil {
		return nil, err
	}
	if edges == nil {
		return []relationship{}, nil
	}
	return edges, nil
}

// createRelationshipHandler creates a directed relationship edge between two campaign
// entities. Only the campaign owner (DM) may create edges. Players receive 403.
func createRelationshipHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createRelationshipRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	if req.SourceID == "" || req.TargetID == "" || req.Kind == "" || req.Score == nil {
		writeError(w, http.StatusBadRequest, "invalid relationship")
		return
	}
	if req.SourceID == req.TargetID {
		writeError(w, http.StatusBadRequest, "invalid relationship")
		return
	}
	if *req.Score < -100 || *req.Score > 100 {
		writeError(w, http.StatusBadRequest, "invalid score")
		return
	}

	sourceExists, err := campaignEntityExists(campaignID, req.SourceID)
	if err != nil {
		log.Printf("relationship entity query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !sourceExists {
		writeError(w, http.StatusNotFound, "entity not found")
		return
	}
	targetExists, err := campaignEntityExists(campaignID, req.TargetID)
	if err != nil {
		log.Printf("relationship entity query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !targetExists {
		writeError(w, http.StatusNotFound, "entity not found")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_relationships WHERE campaign_id=%s AND source_id=%s AND target_id=%s AND kind=%s LIMIT 1;",
		sq(campaignID), sq(req.SourceID), sq(req.TargetID), sq(req.Kind)))
	if err != nil {
		log.Printf("relationship exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "relationship already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_relationships (campaign_id, source_id, target_id, kind, score) VALUES (%s, %s, %s, %s, %d);",
		sq(campaignID), sq(req.SourceID), sq(req.TargetID), sq(req.Kind), *req.Score)); err != nil {
		log.Printf("relationship insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, relationship{
		SourceID: req.SourceID,
		TargetID: req.TargetID,
		Kind:     req.Kind,
		Score:    *req.Score,
	})
}

// updateRelationshipHandler updates the score of an existing directed relationship
// edge. Only the campaign owner (DM) may update edges. Players receive 403.
func updateRelationshipHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	sourceID := r.PathValue("source_id")
	targetID := r.PathValue("target_id")
	kind := r.PathValue("kind")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req updateRelationshipRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Score == nil || *req.Score < -100 || *req.Score > 100 {
		writeError(w, http.StatusBadRequest, "invalid score")
		return
	}

	edge, ok, err := queryRelationship(campaignID, sourceID, targetID, kind)
	if err != nil {
		log.Printf("relationship update query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "relationship not found")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_relationships SET score=%d WHERE campaign_id=%s AND source_id=%s AND target_id=%s AND kind=%s;",
		*req.Score, sq(campaignID), sq(sourceID), sq(targetID), sq(kind))); err != nil {
		log.Printf("relationship update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, relationship{
		SourceID: edge.SourceID,
		TargetID: edge.TargetID,
		Kind:     edge.Kind,
		Score:    *req.Score,
	})
}

// listRelationshipsHandler returns all relationship edges for a campaign in
// insertion order. It is available to any authenticated campaign member or the owner.
func listRelationshipsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	edges, err := queryRelationships(campaignID)
	if err != nil {
		log.Printf("relationships list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, relationshipListResponse{Edges: edges})
}
