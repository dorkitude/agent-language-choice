package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

type scene struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Status string `json:"status"`
}

// queryScene loads a scene by id within a specific campaign. The caller must
// hold dbMu.
func queryScene(campaignID, sceneID string) (*scene, bool, error) {
	var scenes []scene
	if err := queryRows(fmt.Sprintf("SELECT id, name, status FROM campaign_scenes WHERE id=%s AND campaign_id=%s LIMIT 1;", sq(sceneID), sq(campaignID)), &scenes); err != nil {
		return nil, false, err
	}
	if len(scenes) == 0 {
		return nil, false, nil
	}
	return &scenes[0], true, nil
}

// createSceneRequest binds the payload for a new scene.
type createSceneRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// createSceneResponse is the shape returned after a successful scene creation.
type createSceneResponse struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Status string `json:"status"`
}

// createSceneHandler lets the campaign owner create a new scene for a play
// campaign. Only the owner may call it; duplicate scene ids within the
// campaign return 409.
func createSceneHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createSceneRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "invalid scene")
		return
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_scenes WHERE id=%s AND campaign_id=%s LIMIT 1;", sq(req.ID), sq(campaignID)))
	if err != nil {
		log.Printf("scene exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "scene already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_scenes (id, campaign_id, name, status) VALUES (%s, %s, %s, 'open');",
		sq(req.ID), sq(campaignID), sq(req.Name))); err != nil {
		log.Printf("scene insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, createSceneResponse{
		ID:     req.ID,
		Name:   req.Name,
		Status: "open",
	})
}

// enterSceneResponse is the shape returned after the owner enters a scene.
type enterSceneResponse struct {
	CurrentSceneID string `json:"current_scene_id"`
	Name           string `json:"name"`
}

// enterSceneHandler sets the campaign's current scene. Only the owner may
// call it, and the scene must be open.
func enterSceneHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	sceneID := r.PathValue("scene_id")

	owner, ok := requireCampaignOwner(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("enter scene campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	scene, ok, err := queryScene(campaignID, sceneID)
	if err != nil {
		log.Printf("enter scene query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "scene not found")
		return
	}
	if scene.Status != "open" {
		writeError(w, http.StatusConflict, "scene is closed")
		return
	}

	nextSeq, err := nextNarrationSequence(campaignID)
	if err != nil {
		log.Printf("enter scene sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (%s, %d, 'scene', %s, %s);",
		sq(campaignID), nextSeq, sq(owner), sq(sceneID))); err != nil {
		log.Printf("enter scene insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET current_scene_id=%s, current_location_id=%s WHERE id=%s;",
		sq(sceneID), sq(sceneID), sq(campaignID))); err != nil {
		log.Printf("enter scene update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, enterSceneResponse{
		CurrentSceneID: sceneID,
		Name:           scene.Name,
	})
}

// closeSceneResponse is the shape returned after the owner closes a scene.
type closeSceneResponse struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}

// closeSceneHandler marks a campaign scene as closed. Only the owner may
// call it. Closing the current scene means the campaign has no open current
// scene.
func closeSceneHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	sceneID := r.PathValue("scene_id")

	owner, ok := requireCampaignOwner(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("close scene campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	scene, ok, err := queryScene(campaignID, sceneID)
	if err != nil {
		log.Printf("close scene query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "scene not found")
		return
	}

	if scene.Status != "closed" {
		if err := dbExec(fmt.Sprintf("UPDATE campaign_scenes SET status='closed' WHERE id=%s AND campaign_id=%s;",
			sq(sceneID), sq(campaignID))); err != nil {
			log.Printf("close scene update error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	if campaign.CurrentSceneID == sceneID {
		if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET current_scene_id=NULL WHERE id=%s;", sq(campaignID))); err != nil {
			log.Printf("close scene current reset error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	writeJSON(w, http.StatusOK, closeSceneResponse{
		ID:     sceneID,
		Status: "closed",
	})
}

// getCurrentSceneHandler returns the campaign's open current scene for any
// owner or member. If no current scene is set, or the current scene is not
// open, it returns 404.
func getCurrentSceneHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("current scene campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.CurrentSceneID == "" {
		writeError(w, http.StatusNotFound, "no current scene")
		return
	}

	currentScene, ok, err := queryScene(campaignID, campaign.CurrentSceneID)
	if err != nil {
		log.Printf("current scene query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok || currentScene.Status != "open" {
		writeError(w, http.StatusNotFound, "no current scene")
		return
	}

	writeJSON(w, http.StatusOK, scene{
		ID:     currentScene.ID,
		Name:   currentScene.Name,
		Status: currentScene.Status,
	})
}

// campaignLocation is a node in the owner's deterministic location graph.
