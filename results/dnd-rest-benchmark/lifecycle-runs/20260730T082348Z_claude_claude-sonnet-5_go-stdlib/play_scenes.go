package main

import (
	"encoding/json"
	"net/http"
)

type playScene struct {
	ID     string
	Name   string
	Status string
}

type playLocation struct {
	ID          string
	Name        string
	Connections []*playLocationConnection
}

type playLocationConnection struct {
	ToID        string
	TravelTurns int
}

func playSceneResponse(s *playScene) map[string]interface{} {
	return map[string]interface{}{
		"id":     s.ID,
		"name":   s.Name,
		"status": s.Status,
	}
}

// handleCreateScene creates a new scene under a campaign. Only the owner may
// call this; duplicate scene ids return 409.
func handleCreateScene(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "id and name are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may create a scene")
		return
	}
	if c.Scenes == nil {
		c.Scenes = map[string]*playScene{}
	}
	if _, exists := c.Scenes[req.ID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "scene id already exists")
		return
	}

	scene := &playScene{ID: req.ID, Name: req.Name, Status: "open"}
	c.Scenes[scene.ID] = scene
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playSceneResponse(scene))
}

// handleEnterScene sets the campaign's current scene. Only the owner may
// call this; closed scenes may not be entered.
func handleEnterScene(w http.ResponseWriter, r *http.Request, campaignID, sceneID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may enter a scene")
		return
	}
	scene, exists := c.Scenes[sceneID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "scene not found")
		return
	}
	if scene.Status != "open" {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "closed scenes may not be entered")
		return
	}

	c.CurrentSceneID = scene.ID
	c.Events = append(c.Events, &playEvent{
		Sequence: len(c.Events) + 1,
		Kind:     "scene",
		Actor:    username,
		Text:     scene.ID,
	})
	resp := map[string]interface{}{
		"current_scene_id": scene.ID,
		"name":             scene.Name,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handleCloseScene marks a scene closed. Only the owner may call this.
func handleCloseScene(w http.ResponseWriter, r *http.Request, campaignID, sceneID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may close a scene")
		return
	}
	scene, exists := c.Scenes[sceneID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "scene not found")
		return
	}

	scene.Status = "closed"
	resp := map[string]interface{}{
		"id":     scene.ID,
		"status": scene.Status,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handleCurrentScene returns the open current scene for any campaign member.
// If no scene is currently set (or the set scene is no longer open), it
// returns 404.
func handleCurrentScene(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only the owner or a member may view the current scene")
		return
	}
	var scene *playScene
	if c.CurrentSceneID != "" {
		scene = c.Scenes[c.CurrentSceneID]
	}
	if scene == nil || scene.Status != "open" {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "no current scene")
		return
	}
	resp := playSceneResponse(scene)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func playLocationResponse(loc *playLocation) map[string]interface{} {
	return map[string]interface{}{
		"id":   loc.ID,
		"name": loc.Name,
	}
}

// handleCreateLocation creates a new location under a campaign's location
// graph. Only the owner may call this; duplicate location ids return 409.
func handleCreateLocation(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "id and name are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may create a location")
		return
	}
	if c.Locations == nil {
		c.Locations = map[string]*playLocation{}
	}
	if _, exists := c.Locations[req.ID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "location id already exists")
		return
	}

	loc := &playLocation{ID: req.ID, Name: req.Name}
	c.Locations[loc.ID] = loc
	if c.CurrentLocationID == "" {
		c.CurrentLocationID = loc.ID
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playLocationResponse(loc))
}

// handleCreateLocationConnection adds a directed connection from fromID to
// another location. Only the owner may call this; connections to a missing
// destination or an already-connected destination return 400.
func handleCreateLocationConnection(w http.ResponseWriter, r *http.Request, campaignID, fromID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		ToID        string `json:"to_id"`
		TravelTurns *int   `json:"travel_turns"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ToID == "" || req.TravelTurns == nil {
		writeError(w, http.StatusBadRequest, "to_id and travel_turns are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may create a connection")
		return
	}
	from, exists := c.Locations[fromID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "source location not found")
		return
	}
	if _, exists := c.Locations[req.ToID]; !exists {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "destination location not found")
		return
	}
	for _, conn := range from.Connections {
		if conn.ToID == req.ToID {
			playMu.Unlock()
			writeError(w, http.StatusBadRequest, "destination already connected")
			return
		}
	}

	conn := &playLocationConnection{ToID: req.ToID, TravelTurns: *req.TravelTurns}
	from.Connections = append(from.Connections, conn)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"from_id":      fromID,
		"to_id":        conn.ToID,
		"travel_turns": conn.TravelTurns,
	})
}

// handleLocationTravel returns the valid outbound connections from a
// location, visible to the owner or any campaign member.
func handleLocationTravel(w http.ResponseWriter, r *http.Request, campaignID, locID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only the owner or a member may view travel")
		return
	}
	loc, exists := c.Locations[locID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "location not found")
		return
	}

	destinations := make([]map[string]interface{}, 0, len(loc.Connections))
	for _, conn := range loc.Connections {
		to := c.Locations[conn.ToID]
		if to == nil {
			continue
		}
		destinations = append(destinations, map[string]interface{}{
			"id":           to.ID,
			"name":         to.Name,
			"travel_turns": conn.TravelTurns,
		})
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"destinations": destinations})
}
