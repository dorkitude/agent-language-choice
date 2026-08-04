package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createPlayNPCHandler creates a new DM-managed NPC for a play campaign. Only
// the campaign owner (DM) may create NPCs. npc_id, name, agenda, and
// public_status are required nonempty strings. Duplicate npc_id values within
// the same campaign return 409.
func createPlayNPCHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create npcs")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create npcs")
		return
	}

	var req npcCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.NPCID) == "" {
		badRequest(w, "npc_id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}
	if strings.TrimSpace(req.Agenda) == "" {
		badRequest(w, "agenda is required")
		return
	}
	if strings.TrimSpace(req.PublicStatus) == "" {
		badRequest(w, "public_status is required")
		return
	}

	if err := dbCreatePlayNPC(id, req.NPCID, req.Name, req.Agenda, req.PublicStatus); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "npc_id already exists")
			return
		}
		log.Printf("create play npc: %v", err)
		badRequest(w, "failed to create npc")
		return
	}

	writeJSON(w, http.StatusCreated, playNPC{
		NPCID:        req.NPCID,
		Name:         req.Name,
		Agenda:       req.Agenda,
		PublicStatus: req.PublicStatus,
	})
}

// updatePlayNPCAgendaHandler updates a play NPC's private agenda and public
// status. Only the campaign owner (DM) may update NPCs. agenda and public_status
// are required nonempty strings. Unknown NPCs return 404.
func updatePlayNPCAgendaHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can update npcs")
		return
	}

	id := r.PathValue("id")
	npcID := r.PathValue("npc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can update npcs")
		return
	}

	var req npcAgendaUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Agenda) == "" {
		badRequest(w, "agenda is required")
		return
	}
	if strings.TrimSpace(req.PublicStatus) == "" {
		badRequest(w, "public_status is required")
		return
	}

	npc, err := dbUpdatePlayNPCAgenda(id, npcID, req.Agenda, req.PublicStatus)
	if err != nil {
		log.Printf("update play npc agenda: %v", err)
		badRequest(w, "failed to update npc")
		return
	}
	if npc == nil {
		notFound(w, "npc not found")
		return
	}

	writeJSON(w, http.StatusOK, npc)
}

// getPlayNPCHandler reads a single play NPC. It is available to any
// authenticated campaign member. DM responses include the private agenda; player
// responses omit it.
func getPlayNPCHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	npcID := r.PathValue("npc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	npc, err := dbGetPlayNPC(id, npcID)
	if err != nil {
		log.Printf("get play npc: %v", err)
		badRequest(w, "failed to read npc")
		return
	}
	if npc == nil {
		notFound(w, "npc not found")
		return
	}

	if p.Owner == u.Username {
		writeJSON(w, http.StatusOK, npc)
		return
	}
	writeJSON(w, http.StatusOK, npcPublicResponse{
		NPCID:        npc.NPCID,
		Name:         npc.Name,
		PublicStatus: npc.PublicStatus,
	})
}

// createPlayNPCDialogueHandler appends an attributed dialogue entry to a
// campaign NPC. Only the campaign owner (DM) may append dialogue.
// dialogue_id, speaker, and text are required nonempty strings. visibility
// must be exactly public or private. Duplicate dialogue_id values within the
// same NPC return 409. Unknown NPCs return 404.
func createPlayNPCDialogueHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can add dialogue")
		return
	}

	id := r.PathValue("id")
	npcID := r.PathValue("npc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can add dialogue")
		return
	}

	var req dialogueRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.DialogueID) == "" {
		badRequest(w, "dialogue_id is required")
		return
	}
	if strings.TrimSpace(req.Speaker) == "" {
		badRequest(w, "speaker is required")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}
	if req.Visibility != "public" && req.Visibility != "private" {
		badRequest(w, "visibility must be public or private")
		return
	}

	npc, err := dbGetPlayNPC(id, npcID)
	if err != nil {
		log.Printf("get play npc: %v", err)
		badRequest(w, "failed to read npc")
		return
	}
	if npc == nil {
		notFound(w, "npc not found")
		return
	}

	if err := dbCreatePlayNPCDialogue(id, npcID, req.DialogueID, req.Speaker, req.Text, req.Visibility); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "dialogue_id already exists")
			return
		}
		log.Printf("create play npc dialogue: %v", err)
		badRequest(w, "failed to create dialogue")
		return
	}

	writeJSON(w, http.StatusCreated, dialogueEntry{
		DialogueID: req.DialogueID,
		Speaker:    req.Speaker,
		Text:       req.Text,
		Visibility: req.Visibility,
	})
}

// getPlayNPCDialogueHandler reads a campaign NPC's dialogue history. It is
// available to any authenticated campaign member. The DM sees all entries in
// insertion order, including public and private entries. Players see only
// public entries. Unknown NPCs return 404.
func getPlayNPCDialogueHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	npcID := r.PathValue("npc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	npc, err := dbGetPlayNPC(id, npcID)
	if err != nil {
		log.Printf("get play npc: %v", err)
		badRequest(w, "failed to read npc")
		return
	}
	if npc == nil {
		notFound(w, "npc not found")
		return
	}

	entries, err := dbGetPlayNPCDialogue(id, npcID, p.Owner != u.Username)
	if err != nil {
		log.Printf("get play npc dialogue: %v", err)
		badRequest(w, "failed to read dialogue")
		return
	}

	writeJSON(w, http.StatusOK, dialogueResponse{
		NPCID:   npcID,
		Entries: entries,
	})
}
