package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playNPC is a DM-managed campaign NPC record: agenda is dm-private, while
// public_status is visible to players.
type playNPC struct {
	NPCID        string
	Name         string
	Agenda       string
	PublicStatus string
	Dialogue     []*playNPCDialogueEntry
}

// playNPCDialogueEntry is an attributed line of NPC dialogue; private entries
// are visible only to the campaign dm.
type playNPCDialogueEntry struct {
	DialogueID string
	Speaker    string
	Text       string
	Visibility string
}

func playNPCDialogueEntryResponse(e *playNPCDialogueEntry) map[string]interface{} {
	return map[string]interface{}{
		"dialogue_id": e.DialogueID,
		"speaker":     e.Speaker,
		"text":        e.Text,
		"visibility":  e.Visibility,
	}
}

func playNPCDMResponse(n *playNPC) map[string]interface{} {
	return map[string]interface{}{
		"npc_id":        n.NPCID,
		"name":          n.Name,
		"agenda":        n.Agenda,
		"public_status": n.PublicStatus,
	}
}

func playNPCPlayerResponse(n *playNPC) map[string]interface{} {
	return map[string]interface{}{
		"npc_id":        n.NPCID,
		"name":          n.Name,
		"public_status": n.PublicStatus,
	}
}

// handlePlayCampaignNPCSub routes the "npcs" and "npcs/..." sub-paths of a
// play campaign. It returns false if rest does not name an npc path, so the
// caller can fall through to its own routing.
func handlePlayCampaignNPCSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "npcs" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreatePlayNPC(w, r, campaignID)
		return true
	}
	if !strings.HasPrefix(rest, "npcs/") {
		return false
	}
	npcRest := strings.TrimPrefix(rest, "npcs/")

	if npcID, ok := strings.CutSuffix(npcRest, "/agenda"); ok && npcID != "" {
		if r.Method != http.MethodPut {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleUpdatePlayNPCAgenda(w, r, campaignID, npcID)
		return true
	}
	if npcID, ok := strings.CutSuffix(npcRest, "/dialogue"); ok && npcID != "" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayNPCDialogue(w, r, campaignID, npcID)
		case http.MethodGet:
			handleListPlayNPCDialogue(w, r, campaignID, npcID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if npcRest == "" || strings.Contains(npcRest, "/") {
		return false
	}
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return true
	}
	handleGetPlayNPC(w, r, campaignID, npcRest)
	return true
}

// handleCreatePlayNPC lets the campaign dm create a new NPC record. Only the
// dm may call this; npc_id, name, agenda, and public_status must all be
// nonempty strings. Duplicate npc ids return 409.
func handleCreatePlayNPC(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		NPCID        string `json:"npc_id"`
		Name         string `json:"name"`
		Agenda       string `json:"agenda"`
		PublicStatus string `json:"public_status"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.NPCID == "" || req.Name == "" || req.Agenda == "" || req.PublicStatus == "" {
		writeError(w, http.StatusBadRequest, "npc_id, name, agenda, and public_status are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create npcs")
		return
	}
	if c.NPCs == nil {
		c.NPCs = make(map[string]*playNPC)
	}
	if _, exists := c.NPCs[req.NPCID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "npc id already exists")
		return
	}

	n := &playNPC{
		NPCID:        req.NPCID,
		Name:         req.Name,
		Agenda:       req.Agenda,
		PublicStatus: req.PublicStatus,
	}
	c.NPCs[req.NPCID] = n
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playNPCDMResponse(n))
}

// handleUpdatePlayNPCAgenda lets the campaign dm update an NPC's agenda and
// public status. Only the dm may call this; unknown npcs return 404.
func handleUpdatePlayNPCAgenda(w http.ResponseWriter, r *http.Request, campaignID, npcID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Agenda       string `json:"agenda"`
		PublicStatus string `json:"public_status"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Agenda == "" || req.PublicStatus == "" {
		writeError(w, http.StatusBadRequest, "agenda and public_status are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may update an npc agenda")
		return
	}
	n := c.NPCs[npcID]
	if n == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}

	n.Agenda = req.Agenda
	n.PublicStatus = req.PublicStatus
	resp := playNPCDMResponse(n)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handleGetPlayNPC returns an NPC record. Any authenticated campaign member
// may call this; the dm sees the private agenda, players do not.
func handleGetPlayNPC(w http.ResponseWriter, r *http.Request, campaignID, npcID string) {
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
		writeError(w, http.StatusForbidden, "only the owner or a member may view npcs")
		return
	}
	n := c.NPCs[npcID]
	if n == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}
	var resp map[string]interface{}
	if c.Owner == username {
		resp = playNPCDMResponse(n)
	} else {
		resp = playNPCPlayerResponse(n)
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handleCreatePlayNPCDialogue lets the campaign dm append an attributed
// dialogue entry to an npc. dialogue_id, speaker, and text must all be
// nonempty strings, visibility must be "public" or "private", unknown npcs
// return 404, and duplicate dialogue_id values within the same npc return 409.
func handleCreatePlayNPCDialogue(w http.ResponseWriter, r *http.Request, campaignID, npcID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		DialogueID string `json:"dialogue_id"`
		Speaker    string `json:"speaker"`
		Text       string `json:"text"`
		Visibility string `json:"visibility"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.DialogueID == "" || req.Speaker == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "dialogue_id, speaker, and text are required")
		return
	}
	if req.Visibility != "public" && req.Visibility != "private" {
		writeError(w, http.StatusBadRequest, "visibility must be public or private")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may append npc dialogue")
		return
	}
	n := c.NPCs[npcID]
	if n == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}
	for _, e := range n.Dialogue {
		if e.DialogueID == req.DialogueID {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "dialogue id already exists")
			return
		}
	}

	e := &playNPCDialogueEntry{
		DialogueID: req.DialogueID,
		Speaker:    req.Speaker,
		Text:       req.Text,
		Visibility: req.Visibility,
	}
	n.Dialogue = append(n.Dialogue, e)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playNPCDialogueEntryResponse(e))
}

// handleListPlayNPCDialogue returns an npc's dialogue history. Any
// authenticated campaign member may call this; the dm sees all entries while
// players only see entries with public visibility. Unknown npcs return 404.
func handleListPlayNPCDialogue(w http.ResponseWriter, r *http.Request, campaignID, npcID string) {
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
		writeError(w, http.StatusForbidden, "only the owner or a member may view npc dialogue")
		return
	}
	n := c.NPCs[npcID]
	if n == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}
	isDM := c.Owner == username
	entries := make([]map[string]interface{}, 0, len(n.Dialogue))
	for _, e := range n.Dialogue {
		if !isDM && e.Visibility != "public" {
			continue
		}
		entries = append(entries, playNPCDialogueEntryResponse(e))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"npc_id":  npcID,
		"entries": entries,
	})
}
