package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// npcDialogueEntry is a durable dialogue line attributed to a campaign NPC.
// The visibility field is either "public" or "private".
type npcDialogueEntry struct {
	DialogueID string `json:"dialogue_id"`
	Speaker    string `json:"speaker"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// createNPCDialogueRequest binds the payload for appending NPC dialogue.
type createNPCDialogueRequest struct {
	DialogueID string `json:"dialogue_id"`
	Speaker    string `json:"speaker"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// npcDialogueResponse is the shape returned for an NPC dialogue query.
type npcDialogueResponse struct {
	NPCID   string             `json:"npc_id"`
	Entries []npcDialogueEntry `json:"entries"`
}

// queryNPCDialogueEntry loads a single dialogue entry by campaign, npc, and
// dialogue id. The caller must hold dbMu.
func queryNPCDialogueEntry(campaignID, npcID, dialogueID string) (*npcDialogueEntry, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT dialogue_id, speaker, text, visibility FROM npc_dialogue_entries WHERE campaign_id=%s AND npc_id=%s AND dialogue_id=%s LIMIT 1;", sq(campaignID), sq(npcID), sq(dialogueID)))
	if err != nil {
		return nil, false, err
	}
	var rows []npcDialogueEntry
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// queryNPCDialogueEntries loads all dialogue entries for a campaign NPC in
// insertion order. The caller must hold dbMu.
func queryNPCDialogueEntries(campaignID, npcID string) ([]npcDialogueEntry, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT dialogue_id, speaker, text, visibility FROM npc_dialogue_entries WHERE campaign_id=%s AND npc_id=%s ORDER BY id;", sq(campaignID), sq(npcID)))
	if err != nil {
		return nil, err
	}
	var entries []npcDialogueEntry
	if err := json.Unmarshal(out, &entries); err != nil {
		return nil, err
	}
	if entries == nil {
		return []npcDialogueEntry{}, nil
	}
	return entries, nil
}

// createNPCDialogueHandler lets the campaign DM append attributed dialogue to
// an NPC history. Only the campaign owner may call it. Unknown NPCs return
// 404. Required fields and visibility values are validated, and duplicate
// dialogue_id values within the same NPC are rejected with 409.
func createNPCDialogueHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	npcID := r.PathValue("npc_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createNPCDialogueRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.DialogueID == "" || req.Speaker == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid dialogue")
		return
	}
	if req.Visibility != "public" && req.Visibility != "private" {
		writeError(w, http.StatusBadRequest, "invalid visibility")
		return
	}

	npc, ok, err := queryCampaignNPC(campaignID, npcID)
	if err != nil {
		log.Printf("dialogue npc query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}
	_ = npc

	_, exists, err := queryNPCDialogueEntry(campaignID, npcID, req.DialogueID)
	if err != nil {
		log.Printf("dialogue exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "dialogue already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO npc_dialogue_entries (campaign_id, npc_id, dialogue_id, speaker, text, visibility) VALUES (%s, %s, %s, %s, %s, %s);",
		sq(campaignID), sq(npcID), sq(req.DialogueID), sq(req.Speaker), sq(req.Text), sq(req.Visibility))); err != nil {
		log.Printf("dialogue insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, npcDialogueEntry{
		DialogueID: req.DialogueID,
		Speaker:    req.Speaker,
		Text:       req.Text,
		Visibility: req.Visibility,
	})
}

// getNPCDialogueHandler returns an NPC's dialogue history to an authenticated
// campaign member. Unknown NPCs return 404. The DM receives all entries in
// insertion order; players receive only public entries.
func getNPCDialogueHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	npcID := r.PathValue("npc_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("dialogue get campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	_, ok, err = queryCampaignNPC(campaignID, npcID)
	if err != nil {
		log.Printf("dialogue get npc query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}

	entries, err := queryNPCDialogueEntries(campaignID, npcID)
	if err != nil {
		log.Printf("dialogue get entries query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if campaign.Owner != username {
		public := make([]npcDialogueEntry, 0, len(entries))
		for _, e := range entries {
			if e.Visibility == "public" {
				public = append(public, e)
			}
		}
		entries = public
	}

	writeJSON(w, http.StatusOK, npcDialogueResponse{
		NPCID:   npcID,
		Entries: entries,
	})
}
