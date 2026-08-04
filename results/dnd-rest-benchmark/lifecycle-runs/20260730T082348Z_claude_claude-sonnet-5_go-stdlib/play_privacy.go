package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playNote is a campaign note authored by a member, visible either only to
// its owner ("private") or to the whole party ("party"). The dm can always
// read every note regardless of visibility.
type playNote struct {
	NoteID     string
	Text       string
	Visibility string
	Owner      string
}

func playNoteResponse(n *playNote) map[string]interface{} {
	return map[string]interface{}{
		"note_id":    n.NoteID,
		"text":       n.Text,
		"visibility": n.Visibility,
		"owner":      n.Owner,
	}
}

// playWhisper is a private message sent between two characters in a play
// campaign. The dm can always read every whisper; players see only whispers
// where their owned character is the sender or recipient.
type playWhisper struct {
	WhisperID       string
	FromCharacterID string
	ToCharacterID   string
	Text            string
}

func playWhisperResponse(w *playWhisper) map[string]interface{} {
	return map[string]interface{}{
		"whisper_id":        w.WhisperID,
		"from_character_id": w.FromCharacterID,
		"to_character_id":   w.ToCharacterID,
		"text":              w.Text,
	}
}

// findPlayMemberByOwner locates the member currently owned by username within
// c, following ownership transfers via playMemberOwner.
func findPlayMemberByOwner(c *playCampaign, username string) *playMember {
	for _, m := range c.Members {
		if playMemberOwner(m) == username {
			return m
		}
	}
	return nil
}

// handlePlayCampaignNotesSub routes the "notes" and "notes/..." sub-paths of
// a play campaign. It returns false if rest does not name a recognized notes
// path, so the caller can fall through to its own routing.
func handlePlayCampaignNotesSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "notes" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayNote(w, r, campaignID)
		case http.MethodGet:
			handleListPlayNotes(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if noteID, ok := strings.CutPrefix(rest, "notes/"); ok && noteID != "" {
		switch r.Method {
		case http.MethodGet:
			handleGetPlayNote(w, r, campaignID, noteID)
		case http.MethodPut:
			handleUpdatePlayNote(w, r, campaignID, noteID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	return false
}

var validNoteVisibility = map[string]bool{"private": true, "party": true}

type playNoteRequest struct {
	NoteID     string `json:"note_id"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// handleCreatePlayNote lets an authenticated campaign member (or the dm)
// create a note. Owner is always derived from the authenticated actor.
func handleCreatePlayNote(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playNoteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.NoteID == "" || req.Text == "" || !validNoteVisibility[req.Visibility] {
		writeError(w, http.StatusBadRequest, "note_id and text must be nonempty, and visibility must be private or party")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm or a member may create notes")
		return
	}
	if c.Notes == nil {
		c.Notes = make(map[string]*playNote)
	}
	if _, exists := c.Notes[req.NoteID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "note_id already exists")
		return
	}

	rec := &playNote{
		NoteID:     req.NoteID,
		Text:       req.Text,
		Visibility: req.Visibility,
		Owner:      username,
	}
	c.Notes[req.NoteID] = rec
	c.NoteOrder = append(c.NoteOrder, req.NoteID)
	resp := playNoteResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleListPlayNotes returns campaign notes in creation order. The campaign
// dm sees all notes; players see all party notes and only their own private
// notes.
func handleListPlayNotes(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the dm or a member may view notes")
		return
	}

	isDM := c.Owner == username
	notes := make([]map[string]interface{}, 0, len(c.NoteOrder))
	for _, noteID := range c.NoteOrder {
		rec := c.Notes[noteID]
		if isDM || rec.Visibility == "party" || rec.Owner == username {
			notes = append(notes, playNoteResponse(rec))
		}
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"notes": notes})
}

// handleGetPlayNote returns a single note when readable: the dm may read any
// note, and a member may read any party note plus their own private notes.
func handleGetPlayNote(w http.ResponseWriter, r *http.Request, campaignID, noteID string) {
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
		writeError(w, http.StatusForbidden, "only the dm or a member may view notes")
		return
	}
	rec := c.Notes[noteID]
	if rec == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "note not found")
		return
	}
	isDM := c.Owner == username
	if !isDM && rec.Visibility == "private" && rec.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "this note is private to its owner")
		return
	}
	resp := playNoteResponse(rec)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

type playNoteUpdateRequest struct {
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// handleUpdatePlayNote lets only the note owner update text and visibility.
// The dm may read every note but does not override ownership for updates.
func handleUpdatePlayNote(w http.ResponseWriter, r *http.Request, campaignID, noteID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playNoteUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" || !validNoteVisibility[req.Visibility] {
		writeError(w, http.StatusBadRequest, "text must be nonempty, and visibility must be private or party")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm or a member may update notes")
		return
	}
	rec := c.Notes[noteID]
	if rec == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "note not found")
		return
	}
	if rec.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the note owner may update this note")
		return
	}

	rec.Text = req.Text
	rec.Visibility = req.Visibility
	resp := playNoteResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCampaignWhispersSub routes the "whispers" sub-path of a play
// campaign. It returns false if rest does not name a recognized whispers
// path, so the caller can fall through to its own routing.
func handlePlayCampaignWhispersSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest != "whispers" {
		return false
	}
	switch r.Method {
	case http.MethodPost:
		handleCreatePlayWhisper(w, r, campaignID)
	case http.MethodGet:
		handleListPlayWhispers(w, r, campaignID)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
	return true
}

type playWhisperRequest struct {
	WhisperID     string `json:"whisper_id"`
	ToCharacterID string `json:"to_character_id"`
	Text          string `json:"text"`
}

// handleCreatePlayWhisper lets a campaign player with an owned character send
// a whisper to another current campaign member's character.
// from_character_id is derived from the sender's owned character.
func handleCreatePlayWhisper(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playWhisperRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.WhisperID == "" || req.ToCharacterID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "whisper_id, to_character_id, and text are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	sender := findPlayMemberByOwner(c, username)
	if sender == nil {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only a campaign player with an owned character may send whispers")
		return
	}
	recipient := findPlayMemberByCharacterID(c, req.ToCharacterID)
	if recipient == nil {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "to_character_id must belong to a current campaign member")
		return
	}
	if c.Whispers == nil {
		c.Whispers = make(map[string]*playWhisper)
	}
	if _, exists := c.Whispers[req.WhisperID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "whisper_id already exists")
		return
	}

	rec := &playWhisper{
		WhisperID:       req.WhisperID,
		FromCharacterID: sender.CharacterID,
		ToCharacterID:   req.ToCharacterID,
		Text:            req.Text,
	}
	c.Whispers[req.WhisperID] = rec
	c.WhisperOrder = append(c.WhisperOrder, req.WhisperID)
	resp := playWhisperResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleListPlayWhispers returns campaign whispers in creation order. The dm
// sees all whispers; players see only whispers where their owned character
// is either the sender or recipient.
func handleListPlayWhispers(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the dm or a member may view whispers")
		return
	}

	isDM := c.Owner == username
	var ownedCharID string
	if !isDM {
		if m := findPlayMemberByOwner(c, username); m != nil {
			ownedCharID = m.CharacterID
		}
	}
	whispers := make([]map[string]interface{}, 0, len(c.WhisperOrder))
	for _, whisperID := range c.WhisperOrder {
		rec := c.Whispers[whisperID]
		if isDM || (ownedCharID != "" && (rec.FromCharacterID == ownedCharID || rec.ToCharacterID == ownedCharID)) {
			whispers = append(whispers, playWhisperResponse(rec))
		}
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"whispers": whispers})
}

// handlePlayCharacterSheet returns a character's basic sheet. Only the
// character owner and campaign dm may read it; other campaign members and
// non-members receive 403.
func handlePlayCharacterSheet(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	owner := playMemberOwner(member)
	isDM := c.Owner == username
	if !isDM && owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character owner or dm may view this sheet")
		return
	}

	resp := map[string]interface{}{
		"character_id":      member.CharacterID,
		"owner":             owner,
		"name":              member.Name,
		"class":             member.Class,
		"level":             1,
		"proficiency_bonus": 2,
		"hp_max":            10,
		"armor_class":       10,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}
