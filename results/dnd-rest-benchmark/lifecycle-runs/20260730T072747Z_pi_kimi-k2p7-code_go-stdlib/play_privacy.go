package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// note is the response shape for a campaign note.
type note struct {
	NoteID     string `json:"note_id"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
	Owner      string `json:"owner"`
}

// createNoteRequest binds the payload for creating a note.
type createNoteRequest struct {
	NoteID     string `json:"note_id"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// updateNoteRequest binds the payload for updating a note.
type updateNoteRequest struct {
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// noteListResponse is the shape returned by the note list endpoint.
type noteListResponse struct {
	Notes []note `json:"notes"`
}

// whisper is the response shape for a campaign whisper.
type whisper struct {
	WhisperID       string `json:"whisper_id"`
	FromCharacterID string `json:"from_character_id"`
	ToCharacterID   string `json:"to_character_id"`
	Text            string `json:"text"`
}

// createWhisperRequest binds the payload for creating a whisper.
type createWhisperRequest struct {
	WhisperID     string `json:"whisper_id"`
	ToCharacterID string `json:"to_character_id"`
	Text          string `json:"text"`
}

// whisperListResponse is the shape returned by the whisper list endpoint.
type whisperListResponse struct {
	Whispers []whisper `json:"whispers"`
}

// characterSheetResponse is the shape returned by the character sheet endpoint.
type characterSheetResponse struct {
	CharacterID      string `json:"character_id"`
	Owner            string `json:"owner"`
	Name             string `json:"name"`
	Class            string `json:"class"`
	Level            int    `json:"level"`
	ProficiencyBonus int    `json:"proficiency_bonus"`
	HPMax            int    `json:"hp_max"`
	ArmorClass       int    `json:"armor_class"`
}

// requireCampaignAccess authenticates the request and authorizes only the
// campaign owner or a campaign member. It returns the username, a bool that is
// true when the caller is the campaign DM, and a bool that is true on success.
// Unknown campaigns return 404.
func requireCampaignAccess(w http.ResponseWriter, r *http.Request, campaignID string) (string, bool, bool) {
	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return "", false, false
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("campaign access user query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false, false
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false, false
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("campaign access campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false, false
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return "", false, false
	}
	if campaign.Owner == username {
		return username, true, true
	}

	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
	if err != nil {
		log.Printf("campaign access member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false, false
	}
	var memberRows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &memberRows); err != nil {
		log.Printf("campaign access member unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false, false
	}
	if len(memberRows) > 0 {
		return username, false, true
	}
	writeError(w, http.StatusForbidden, "forbidden")
	return "", false, false
}

// queryOwnedCharacterID returns the character_id owned by username in the
// campaign, if any. The caller must hold dbMu.
func queryOwnedCharacterID(campaignID, username string) (string, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT character_id FROM play_campaign_members WHERE campaign_id=%s AND username=%s AND owner=%s LIMIT 1;", sq(campaignID), sq(username), sq(username)))
	if err != nil {
		return "", false, err
	}
	var rows []struct {
		CharacterID string `json:"character_id"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return "", false, err
	}
	if len(rows) == 0 {
		return "", false, nil
	}
	return rows[0].CharacterID, true, nil
}

// queryCampaignNote loads a single campaign note by campaign and note id.
// The caller must hold dbMu. It returns nil if the note does not exist.
func queryCampaignNote(campaignID, noteID string) (*note, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT note_id, text, visibility, owner FROM campaign_notes WHERE campaign_id=%s AND note_id=%s LIMIT 1;", sq(campaignID), sq(noteID)))
	if err != nil {
		return nil, false, err
	}
	var rows []note
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// queryCampaignWhisper loads a single campaign whisper by campaign and whisper id.
// The caller must hold dbMu. It returns nil if the whisper does not exist.
func queryCampaignWhisper(campaignID, whisperID string) (*whisper, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT whisper_id, from_character_id, to_character_id, text FROM campaign_whispers WHERE campaign_id=%s AND whisper_id=%s LIMIT 1;", sq(campaignID), sq(whisperID)))
	if err != nil {
		return nil, false, err
	}
	var rows []whisper
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// createNoteHandler lets authenticated campaign members create a note. The
// owner is derived from the authenticated actor.
func createNoteHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, _, ok := requireCampaignAccess(w, r, campaignID)
	if !ok {
		return
	}

	var req createNoteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.NoteID == "" || req.Text == "" || (req.Visibility != "private" && req.Visibility != "party") {
		writeError(w, http.StatusBadRequest, "invalid note")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_notes WHERE campaign_id=%s AND note_id=%s LIMIT 1;", sq(campaignID), sq(req.NoteID)))
	if err != nil {
		log.Printf("create note duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "note already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_notes (campaign_id, note_id, text, visibility, owner, sort_order) VALUES (%s, %s, %s, %s, %s, COALESCE((SELECT MAX(sort_order) FROM campaign_notes WHERE campaign_id=%s), 0) + 1);",
		sq(campaignID), sq(req.NoteID), sq(req.Text), sq(req.Visibility), sq(username), sq(campaignID))); err != nil {
		log.Printf("create note insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, note{
		NoteID:     req.NoteID,
		Text:       req.Text,
		Visibility: req.Visibility,
		Owner:      username,
	})
}

// listNotesHandler returns campaign notes in creation order. The DM sees all
// notes; players see all party notes and only their own private notes.
func listNotesHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, isDM, ok := requireCampaignAccess(w, r, campaignID)
	if !ok {
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT note_id, text, visibility, owner FROM campaign_notes WHERE campaign_id=%s ORDER BY sort_order;", sq(campaignID)))
	if err != nil {
		log.Printf("list notes query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []note
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("list notes unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	notes := make([]note, 0, len(rows))
	for _, n := range rows {
		if isDM || n.Visibility == "party" || n.Owner == username {
			notes = append(notes, n)
		}
	}
	if notes == nil {
		notes = []note{}
	}

	writeJSON(w, http.StatusOK, noteListResponse{Notes: notes})
}

// getNoteHandler returns a single note when readable. Private notes return 403
// to campaign members who are not the owner; the DM can read every note.
func getNoteHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	noteID := r.PathValue("note_id")

	username, isDM, ok := requireCampaignAccess(w, r, campaignID)
	if !ok {
		return
	}

	n, ok, err := queryCampaignNote(campaignID, noteID)
	if err != nil {
		log.Printf("get note query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "note not found")
		return
	}

	if !isDM && n.Visibility == "private" && n.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	writeJSON(w, http.StatusOK, *n)
}

// updateNoteHandler lets only the note owner update text and visibility. The
// DM may read all notes but does not override ownership.
func updateNoteHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	noteID := r.PathValue("note_id")

	username, _, ok := requireCampaignAccess(w, r, campaignID)
	if !ok {
		return
	}

	n, ok, err := queryCampaignNote(campaignID, noteID)
	if err != nil {
		log.Printf("update note query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "note not found")
		return
	}

	if n.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req updateNoteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" || (req.Visibility != "private" && req.Visibility != "party") {
		writeError(w, http.StatusBadRequest, "invalid note")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_notes SET text=%s, visibility=%s WHERE campaign_id=%s AND note_id=%s;",
		sq(req.Text), sq(req.Visibility), sq(campaignID), sq(noteID))); err != nil {
		log.Printf("update note update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, note{
		NoteID:     n.NoteID,
		Text:       req.Text,
		Visibility: req.Visibility,
		Owner:      n.Owner,
	})
}

// createWhisperHandler lets a campaign player with an owned character send a
// whisper to another campaign member's character.
func createWhisperHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, _, ok := requireCampaignAccess(w, r, campaignID)
	if !ok {
		return
	}

	user, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("create whisper user query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok || user.Role != "player" {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	fromCharacterID, ok, err := queryOwnedCharacterID(campaignID, username)
	if err != nil {
		log.Printf("create whisper owned character query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req createWhisperRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.WhisperID == "" || req.ToCharacterID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid whisper")
		return
	}

	toMemberExists, err := queryExists(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND character_id=%s LIMIT 1;", sq(campaignID), sq(req.ToCharacterID)))
	if err != nil {
		log.Printf("create whisper recipient query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !toMemberExists {
		writeError(w, http.StatusBadRequest, "invalid whisper")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_whispers WHERE campaign_id=%s AND whisper_id=%s LIMIT 1;", sq(campaignID), sq(req.WhisperID)))
	if err != nil {
		log.Printf("create whisper duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "whisper already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text, sort_order) VALUES (%s, %s, %s, %s, %s, COALESCE((SELECT MAX(sort_order) FROM campaign_whispers WHERE campaign_id=%s), 0) + 1);",
		sq(campaignID), sq(req.WhisperID), sq(fromCharacterID), sq(req.ToCharacterID), sq(req.Text), sq(campaignID))); err != nil {
		log.Printf("create whisper insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, whisper{
		WhisperID:       req.WhisperID,
		FromCharacterID: fromCharacterID,
		ToCharacterID:   req.ToCharacterID,
		Text:            req.Text,
	})
}

// listWhispersHandler returns campaign whispers in creation order. The DM sees
// all whispers; players see only whispers involving their owned character.
func listWhispersHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, isDM, ok := requireCampaignAccess(w, r, campaignID)
	if !ok {
		return
	}

	ownedCharacterID := ""
	if !isDM {
		id, ok, err := queryOwnedCharacterID(campaignID, username)
		if err != nil {
			log.Printf("list whispers owned character query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if ok {
			ownedCharacterID = id
		}
	}

	out, err := dbQuery(fmt.Sprintf("SELECT whisper_id, from_character_id, to_character_id, text FROM campaign_whispers WHERE campaign_id=%s ORDER BY sort_order;", sq(campaignID)))
	if err != nil {
		log.Printf("list whispers query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []whisper
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("list whispers unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	whispers := make([]whisper, 0, len(rows))
	for _, w := range rows {
		if isDM || w.FromCharacterID == ownedCharacterID || w.ToCharacterID == ownedCharacterID {
			whispers = append(whispers, w)
		}
	}
	if whispers == nil {
		whispers = []whisper{}
	}

	writeJSON(w, http.StatusOK, whisperListResponse{Whispers: whispers})
}

// getCharacterSheetHandler returns the basic character sheet for a campaign
// character. Only the character owner and the campaign DM may read it.
func getCharacterSheetHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	username, isDM, ok := requireCampaignAccess(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("character sheet member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	if !isDM && member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	writeJSON(w, http.StatusOK, characterSheetResponse{
		CharacterID:      characterID,
		Owner:            member.Owner,
		Name:             member.Name,
		Class:            member.Class,
		Level:            1,
		ProficiencyBonus: 2,
		HPMax:            10,
		ArmorClass:       10,
	})
}

// createMessageRequest binds the payload for a new campaign chat message.
type createMessageRequest struct {
	Text string `json:"text"`
}

// createMessageResponse is the exact shape returned after creating a chat
// message. The kind is always "chat" and the actor is the authenticated user.
type createMessageResponse struct {
	Kind  string `json:"kind"`
	Actor string `json:"actor"`
	Text  string `json:"text"`
}

// createMessageHandler lets authenticated campaign members post a chat message.
// Spectator tokens are rejected because requireCampaignAccess only accepts
// session bearer tokens, returning 401 for any other bearer scheme.
func createMessageHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, _, ok := requireCampaignAccess(w, r, campaignID)
	if !ok {
		return
	}

	var req createMessageRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid message")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_messages (campaign_id, actor, kind, text, sort_order) VALUES (%s, %s, 'chat', %s, COALESCE((SELECT MAX(sort_order) FROM campaign_messages WHERE campaign_id=%s), 0) + 1);",
		sq(campaignID), sq(username), sq(req.Text), sq(campaignID))); err != nil {
		log.Printf("create message insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, createMessageResponse{
		Kind:  "chat",
		Actor: username,
		Text:  req.Text,
	})
}
