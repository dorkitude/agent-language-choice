package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

const (
	noteVisibilityPrivate = "private"
	noteVisibilityParty   = "party"
)

// createPlayNoteHandler creates a campaign note. Only authenticated campaign
// members (players with an owned character) may create notes. The owner is
// derived from the authenticated actor.
func createPlayNoteHandler(w http.ResponseWriter, r *http.Request) {
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
	membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if membership == nil {
		forbidden(w, "only campaign members may create notes")
		return
	}

	var req playNoteCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.NoteID) == "" {
		badRequest(w, "note_id is required")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}
	if req.Visibility != noteVisibilityPrivate && req.Visibility != noteVisibilityParty {
		badRequest(w, "visibility must be private or party")
		return
	}

	note := &playNote{
		NoteID:     req.NoteID,
		Text:       req.Text,
		Visibility: req.Visibility,
		Owner:      u.Username,
	}
	if err := dbCreatePlayNote(id, note); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "note already exists")
			return
		}
		log.Printf("create play note: %v", err)
		badRequest(w, "failed to create note")
		return
	}

	writeJSON(w, http.StatusCreated, note)
}

// listPlayNotesHandler lists campaign notes. The DM sees every note; players
// see all party notes and only their own private notes.
func listPlayNotesHandler(w http.ResponseWriter, r *http.Request) {
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

	notes, err := dbListPlayNotes(id)
	if err != nil {
		log.Printf("list play notes: %v", err)
		badRequest(w, "failed to read notes")
		return
	}

	if p.Owner == u.Username {
		writeJSON(w, http.StatusOK, playNotesResponse{Notes: notes})
		return
	}

	filtered := make([]playNote, 0, len(notes))
	for _, n := range notes {
		if n.Visibility == noteVisibilityParty || n.Owner == u.Username {
			filtered = append(filtered, n)
		}
	}
	writeJSON(w, http.StatusOK, playNotesResponse{Notes: filtered})
}

// getPlayNoteHandler reads a single campaign note. Private notes return 403 to
// campaign members who are not the owner; the DM can read every note.
func getPlayNoteHandler(w http.ResponseWriter, r *http.Request) {
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

	noteID := r.PathValue("note_id")
	note, err := dbGetPlayNote(id, noteID)
	if err != nil {
		log.Printf("get play note: %v", err)
		badRequest(w, "failed to read note")
		return
	}
	if note == nil {
		notFound(w, "note not found")
		return
	}

	if note.Visibility == noteVisibilityPrivate && note.Owner != u.Username && p.Owner != u.Username {
		forbidden(w, "not the note owner")
		return
	}

	writeJSON(w, http.StatusOK, note)
}

// updatePlayNoteHandler updates a note's text and visibility. Only the note
// owner may update it; the DM has read access but does not override ownership.
func updatePlayNoteHandler(w http.ResponseWriter, r *http.Request) {
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

	noteID := r.PathValue("note_id")
	note, err := dbGetPlayNote(id, noteID)
	if err != nil {
		log.Printf("get play note: %v", err)
		badRequest(w, "failed to read note")
		return
	}
	if note == nil {
		notFound(w, "note not found")
		return
	}
	if note.Owner != u.Username {
		forbidden(w, "only the note owner may update this note")
		return
	}

	var req playNoteUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}
	if req.Visibility != noteVisibilityPrivate && req.Visibility != noteVisibilityParty {
		badRequest(w, "visibility must be private or party")
		return
	}

	if err := dbUpdatePlayNote(id, noteID, req.Text, req.Visibility); err != nil {
		log.Printf("update play note: %v", err)
		badRequest(w, "failed to update note")
		return
	}

	updated := &playNote{
		NoteID:     note.NoteID,
		Text:       req.Text,
		Visibility: req.Visibility,
		Owner:      note.Owner,
	}
	writeJSON(w, http.StatusOK, updated)
}

// createPlayWhisperHandler creates a character-to-character whisper. The sender
// must be a campaign member with an owned character; from_character_id is
// derived from that membership. The target character must belong to a current
// campaign member.
func createPlayWhisperHandler(w http.ResponseWriter, r *http.Request) {
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

	sender, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if sender == nil {
		forbidden(w, "only campaign members with an owned character may create whispers")
		return
	}

	var req playWhisperCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.WhisperID) == "" {
		badRequest(w, "whisper_id is required")
		return
	}
	if strings.TrimSpace(req.ToCharacterID) == "" {
		badRequest(w, "to_character_id is required")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}

	target, err := dbGetPlayMembershipByCharacterID(id, req.ToCharacterID)
	if err != nil {
		log.Printf("get target character: %v", err)
		badRequest(w, "failed to read target character")
		return
	}
	if target == nil {
		badRequest(w, "to_character_id is not a campaign member")
		return
	}

	whisper := &playWhisper{
		WhisperID:       req.WhisperID,
		FromCharacterID: sender.CharacterID,
		ToCharacterID:   req.ToCharacterID,
		Text:            req.Text,
	}
	if err := dbCreatePlayWhisper(id, whisper); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "whisper already exists")
			return
		}
		log.Printf("create play whisper: %v", err)
		badRequest(w, "failed to create whisper")
		return
	}

	writeJSON(w, http.StatusCreated, whisper)
}

// listPlayWhispersHandler lists campaign whispers. The DM sees all whispers;
// players see only whispers where their owned character is the sender or the
// recipient.
func listPlayWhispersHandler(w http.ResponseWriter, r *http.Request) {
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

	whispers, err := dbListPlayWhispers(id)
	if err != nil {
		log.Printf("list play whispers: %v", err)
		badRequest(w, "failed to read whispers")
		return
	}

	if p.Owner == u.Username {
		writeJSON(w, http.StatusOK, playWhispersResponse{Whispers: whispers})
		return
	}

	viewer, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if viewer == nil {
		forbidden(w, "not a campaign member")
		return
	}

	filtered := make([]playWhisper, 0, len(whispers))
	for _, wh := range whispers {
		if wh.FromCharacterID == viewer.CharacterID || wh.ToCharacterID == viewer.CharacterID {
			filtered = append(filtered, wh)
		}
	}
	writeJSON(w, http.StatusOK, playWhispersResponse{Whispers: filtered})
}

// getCharacterSheetHandler returns the deterministic basic sheet for a
// campaign character. Only the character owner and the campaign DM may read it.
func getCharacterSheetHandler(w http.ResponseWriter, r *http.Request) {
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

	characterID := r.PathValue("character_id")
	m, err := dbGetPlayMembershipByCharacterID(id, characterID)
	if err != nil {
		log.Printf("get character sheet: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if p.Owner != u.Username && m.Username != u.Username {
		forbidden(w, "only the character owner or DM may read this sheet")
		return
	}

	writeJSON(w, http.StatusOK, characterSheetResponse{
		CharacterID:      characterID,
		Owner:            m.Username,
		Name:             m.Name,
		Class:            m.Class,
		Level:            1,
		ProficiencyBonus: 2,
		HPMax:            10,
		ArmorClass:       10,
	})
}
