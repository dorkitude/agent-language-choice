package main

import (
	"net/http"
	"sync"
)

// playNPC is a DM-managed campaign NPC record. Agenda is private to the DM;
// PublicStatus is visible to players.
type playNPC struct {
	CampaignID   string `json:"-"`
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// campaignNPCsMu guards campaignNPCs, the in-memory index mirroring the
// play_npcs table. Keyed by campaign id, then npc id.
var (
	campaignNPCsMu sync.Mutex
	campaignNPCs   = map[string]map[string]*playNPC{}
)

type createPlayNPCRequest struct {
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// createPlayNPCHandler lets the campaign's owning dm create a new NPC record with
// a private agenda and a player-visible public status.
func createPlayNPCHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createPlayNPCRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.NPCID == "" || req.Name == "" || req.Agenda == "" || req.PublicStatus == "" {
		writeError(w, http.StatusBadRequest, "npc_id, name, agenda, and public_status are required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may create npcs")
		return
	}

	campaignNPCsMu.Lock()
	defer campaignNPCsMu.Unlock()

	if campaignNPCs[campaignID] != nil {
		if _, exists := campaignNPCs[campaignID][req.NPCID]; exists {
			writeError(w, http.StatusConflict, "npc_id already exists")
			return
		}
	}

	rec := &playNPC{
		CampaignID:   campaignID,
		NPCID:        req.NPCID,
		Name:         req.Name,
		Agenda:       req.Agenda,
		PublicStatus: req.PublicStatus,
	}
	if err := saveNPCToDB(rec); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save npc")
		return
	}
	if campaignNPCs[campaignID] == nil {
		campaignNPCs[campaignID] = map[string]*playNPC{}
	}
	campaignNPCs[campaignID][req.NPCID] = rec

	writeJSON(w, http.StatusCreated, map[string]any{
		"npc_id":        rec.NPCID,
		"name":          rec.Name,
		"agenda":        rec.Agenda,
		"public_status": rec.PublicStatus,
	})
}

type updateNPCAgendaRequest struct {
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// updateNPCAgendaHandler lets the campaign's owning dm update an NPC's
// private agenda and public status.
func updateNPCAgendaHandler(w http.ResponseWriter, r *http.Request, campaignID, npcID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req updateNPCAgendaRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Agenda == "" || req.PublicStatus == "" {
		writeError(w, http.StatusBadRequest, "agenda and public_status are required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may update npc agendas")
		return
	}

	campaignNPCsMu.Lock()
	defer campaignNPCsMu.Unlock()

	rec, exists := campaignNPCs[campaignID][npcID]
	if !exists {
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}

	rec.Agenda = req.Agenda
	rec.PublicStatus = req.PublicStatus
	if err := saveNPCToDB(rec); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save npc")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"npc_id":        rec.NPCID,
		"name":          rec.Name,
		"agenda":        rec.Agenda,
		"public_status": rec.PublicStatus,
	})
}

// getNPCHandler returns an NPC's current state. Any authenticated campaign
// member may call this; the campaign dm sees the private agenda, players see
// only the public shape.
func getNPCHandler(w http.ResponseWriter, r *http.Request, campaignID, npcID string) {
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

	campaignNPCsMu.Lock()
	defer campaignNPCsMu.Unlock()

	rec, exists := campaignNPCs[campaignID][npcID]
	if !exists {
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}

	if isDM {
		writeJSON(w, http.StatusOK, map[string]any{
			"npc_id":        rec.NPCID,
			"name":          rec.Name,
			"agenda":        rec.Agenda,
			"public_status": rec.PublicStatus,
		})
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"npc_id":        rec.NPCID,
		"name":          rec.Name,
		"public_status": rec.PublicStatus,
	})
}

// playNPCDialogueEntry is one immutable attributed dialogue line for a
// campaign NPC. Private entries are visible only to the campaign dm.
type playNPCDialogueEntry struct {
	CampaignID string `json:"-"`
	NPCID      string `json:"-"`
	DialogueID string `json:"dialogue_id"`
	Speaker    string `json:"speaker"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// campaignNPCDialogueMu guards campaignNPCDialogue, the in-memory index
// mirroring the play_npc_dialogue table. Keyed by campaign id, then npc id,
// holding entries in insertion order.
var (
	campaignNPCDialogueMu sync.Mutex
	campaignNPCDialogue   = map[string]map[string][]*playNPCDialogueEntry{}
)

type createNPCDialogueRequest struct {
	DialogueID string `json:"dialogue_id"`
	Speaker    string `json:"speaker"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// createNPCDialogueHandler lets the campaign's owning dm append an
// attributed dialogue entry to an NPC's history.
func createNPCDialogueHandler(w http.ResponseWriter, r *http.Request, campaignID, npcID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createNPCDialogueRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may append npc dialogue")
		return
	}

	campaignNPCsMu.Lock()
	_, exists := campaignNPCs[campaignID][npcID]
	campaignNPCsMu.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}

	if req.DialogueID == "" || req.Speaker == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "dialogue_id, speaker, and text are required")
		return
	}
	if req.Visibility != "public" && req.Visibility != "private" {
		writeError(w, http.StatusBadRequest, "visibility must be exactly public or private")
		return
	}

	campaignNPCDialogueMu.Lock()
	defer campaignNPCDialogueMu.Unlock()

	if campaignNPCDialogue[campaignID] != nil {
		for _, e := range campaignNPCDialogue[campaignID][npcID] {
			if e.DialogueID == req.DialogueID {
				writeError(w, http.StatusConflict, "dialogue_id already exists")
				return
			}
		}
	}

	entry := &playNPCDialogueEntry{
		CampaignID: campaignID,
		NPCID:      npcID,
		DialogueID: req.DialogueID,
		Speaker:    req.Speaker,
		Text:       req.Text,
		Visibility: req.Visibility,
	}
	entryID := len(campaignNPCDialogue[campaignID][npcID]) + 1
	if err := saveNPCDialogueEntryToDB(entry, entryID); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save dialogue entry")
		return
	}
	if campaignNPCDialogue[campaignID] == nil {
		campaignNPCDialogue[campaignID] = map[string][]*playNPCDialogueEntry{}
	}
	campaignNPCDialogue[campaignID][npcID] = append(campaignNPCDialogue[campaignID][npcID], entry)

	writeJSON(w, http.StatusCreated, map[string]any{
		"dialogue_id": entry.DialogueID,
		"speaker":     entry.Speaker,
		"text":        entry.Text,
		"visibility":  entry.Visibility,
	})
}

// getNPCDialogueHandler returns an NPC's dialogue history. The dm sees every
// entry; players see only entries with public visibility.
func getNPCDialogueHandler(w http.ResponseWriter, r *http.Request, campaignID, npcID string) {
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

	campaignNPCsMu.Lock()
	_, exists := campaignNPCs[campaignID][npcID]
	campaignNPCsMu.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}

	campaignNPCDialogueMu.Lock()
	defer campaignNPCDialogueMu.Unlock()

	entries := campaignNPCDialogue[campaignID][npcID]
	out := make([]map[string]any, 0, len(entries))
	for _, e := range entries {
		if !isDM && e.Visibility != "public" {
			continue
		}
		out = append(out, map[string]any{
			"dialogue_id": e.DialogueID,
			"speaker":     e.Speaker,
			"text":        e.Text,
			"visibility":  e.Visibility,
		})
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"npc_id":  npcID,
		"entries": out,
	})
}
