package main

import (
	"net/http"
	"sync"
)

// requireCampaignAccess reports whether actor may access c's play data as
// either the owning dm or a joined member, writing a 403 and returning
// ok=false otherwise. Callers must already hold playCampaignsMu.
func requireCampaignAccess(w http.ResponseWriter, c *playCampaign, actor *user) (isDM bool, ok bool) {
	isDM = actor.Username == c.Owner
	if !isDM && !isPlayMember(c.ID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return false, false
	}
	return isDM, true
}

// findMemberByOwner looks up the play member whose effective character owner
// is username within campaignID. Callers must already hold playMembersMu.
func findMemberByOwner(campaignID, username string) (*playMember, bool) {
	for _, m := range playMembers[campaignID] {
		if playMemberOwner(m) == username {
			return m, true
		}
	}
	return nil, false
}

// playNote is a campaign note with role-filtered visibility.
type playNote struct {
	CampaignID string
	NoteID     string
	Text       string
	Visibility string
	Owner      string
}

// campaignNotesMu guards campaignNotes, the in-memory index mirroring the
// play_notes table. Keyed by campaign id, holding notes in creation order.
var (
	campaignNotesMu sync.Mutex
	campaignNotes   = map[string][]*playNote{}
)

func noteJSON(n *playNote) map[string]any {
	return map[string]any{
		"note_id":    n.NoteID,
		"text":       n.Text,
		"visibility": n.Visibility,
		"owner":      n.Owner,
	}
}

type createNoteRequest struct {
	NoteID     string `json:"note_id"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// createNoteHandler lets an authenticated campaign member create a note,
// deriving owner from the actor.
func createNoteHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createNoteRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	isDM, ok := requireCampaignAccess(w, c, actor)
	if !ok {
		return
	}
	if !isDM && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "only campaign members may create notes")
		return
	}

	if req.NoteID == "" || req.Text == "" || (req.Visibility != "private" && req.Visibility != "party") {
		writeError(w, http.StatusBadRequest, "note_id and text must be nonempty strings and visibility must be private or party")
		return
	}

	campaignNotesMu.Lock()
	defer campaignNotesMu.Unlock()

	for _, existing := range campaignNotes[campaignID] {
		if existing.NoteID == req.NoteID {
			writeError(w, http.StatusConflict, "note_id already exists in this campaign")
			return
		}
	}

	note := &playNote{
		CampaignID: campaignID,
		NoteID:     req.NoteID,
		Text:       req.Text,
		Visibility: req.Visibility,
		Owner:      actor.Username,
	}
	if err := saveNoteToDB(note); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save note")
		return
	}
	campaignNotes[campaignID] = append(campaignNotes[campaignID], note)

	writeJSON(w, http.StatusCreated, noteJSON(note))
}

// listNotesHandler returns campaign notes. The dm sees every note. Players
// see all party notes and only their own private notes.
func listNotesHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	isDM, ok := requireCampaignAccess(w, c, actor)
	if !ok {
		return
	}

	campaignNotesMu.Lock()
	defer campaignNotesMu.Unlock()

	notes := make([]map[string]any, 0, len(campaignNotes[campaignID]))
	for _, n := range campaignNotes[campaignID] {
		if isDM || n.Visibility == "party" || n.Owner == actor.Username {
			notes = append(notes, noteJSON(n))
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{"notes": notes})
}

// getNoteHandler returns a single note when readable by actor. The dm may
// read every note; other members may only read party notes and their own
// private notes.
func getNoteHandler(w http.ResponseWriter, r *http.Request, campaignID, noteID string) {
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
	isDM, ok := requireCampaignAccess(w, c, actor)
	if !ok {
		return
	}

	campaignNotesMu.Lock()
	defer campaignNotesMu.Unlock()

	var note *playNote
	for _, n := range campaignNotes[campaignID] {
		if n.NoteID == noteID {
			note = n
			break
		}
	}
	if note == nil {
		writeError(w, http.StatusNotFound, "note not found")
		return
	}
	if !isDM && note.Visibility == "private" && note.Owner != actor.Username {
		writeError(w, http.StatusForbidden, "note is private to its owner")
		return
	}

	writeJSON(w, http.StatusOK, noteJSON(note))
}

type updateNoteRequest struct {
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// updateNoteHandler lets only the note owner update its text and visibility.
// The dm may read all notes but does not override ownership for writes.
func updateNoteHandler(w http.ResponseWriter, r *http.Request, campaignID, noteID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req updateNoteRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if _, ok := requireCampaignAccess(w, c, actor); !ok {
		return
	}

	if req.Text == "" || (req.Visibility != "private" && req.Visibility != "party") {
		writeError(w, http.StatusBadRequest, "text must be a nonempty string and visibility must be private or party")
		return
	}

	campaignNotesMu.Lock()
	defer campaignNotesMu.Unlock()

	var note *playNote
	for _, n := range campaignNotes[campaignID] {
		if n.NoteID == noteID {
			note = n
			break
		}
	}
	if note == nil {
		writeError(w, http.StatusNotFound, "note not found")
		return
	}
	if note.Owner != actor.Username {
		writeError(w, http.StatusForbidden, "only the note owner may update it")
		return
	}

	note.Text = req.Text
	note.Visibility = req.Visibility
	if err := saveNoteToDB(note); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save note")
		return
	}

	writeJSON(w, http.StatusOK, noteJSON(note))
}

// playWhisper is a private character-to-character message.
type playWhisper struct {
	CampaignID      string
	WhisperID       string
	FromCharacterID string
	ToCharacterID   string
	Text            string
}

// campaignWhispersMu guards campaignWhispers, the in-memory index mirroring
// the play_whispers table. Keyed by campaign id, holding whispers in
// creation order.
var (
	campaignWhispersMu sync.Mutex
	campaignWhispers   = map[string][]*playWhisper{}
)

func whisperJSON(wh *playWhisper) map[string]any {
	return map[string]any{
		"whisper_id":        wh.WhisperID,
		"from_character_id": wh.FromCharacterID,
		"to_character_id":   wh.ToCharacterID,
		"text":              wh.Text,
	}
}

type createWhisperRequest struct {
	WhisperID     string `json:"whisper_id"`
	ToCharacterID string `json:"to_character_id"`
	Text          string `json:"text"`
}

// createWhisperHandler lets a campaign player with an owned character send a
// whisper to another current campaign member's character.
func createWhisperHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createWhisperRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if _, ok := requireCampaignAccess(w, c, actor); !ok {
		return
	}

	if req.WhisperID == "" || req.ToCharacterID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "whisper_id, to_character_id, and text are required nonempty strings")
		return
	}

	playMembersMu.Lock()
	sender, senderOK := findMemberByOwner(campaignID, actor.Username)
	_, recipientOK := findMemberByCharacterID(campaignID, req.ToCharacterID)
	playMembersMu.Unlock()

	if !senderOK {
		writeError(w, http.StatusForbidden, "must be a campaign player with an owned character")
		return
	}
	if !recipientOK {
		writeError(w, http.StatusBadRequest, "to_character_id must belong to a current campaign member")
		return
	}

	campaignWhispersMu.Lock()
	defer campaignWhispersMu.Unlock()

	for _, existing := range campaignWhispers[campaignID] {
		if existing.WhisperID == req.WhisperID {
			writeError(w, http.StatusConflict, "whisper_id already exists in this campaign")
			return
		}
	}

	wh := &playWhisper{
		CampaignID:      campaignID,
		WhisperID:       req.WhisperID,
		FromCharacterID: sender.CharacterID,
		ToCharacterID:   req.ToCharacterID,
		Text:            req.Text,
	}
	if err := saveWhisperToDB(wh); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save whisper")
		return
	}
	campaignWhispers[campaignID] = append(campaignWhispers[campaignID], wh)

	writeJSON(w, http.StatusCreated, whisperJSON(wh))
}

// listWhispersHandler returns campaign whispers. The dm sees every whisper.
// Players see only whispers where their owned character is the sender or
// recipient.
func listWhispersHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	isDM, ok := requireCampaignAccess(w, c, actor)
	if !ok {
		return
	}

	var ownCharacterID string
	if !isDM {
		playMembersMu.Lock()
		if m, exists := findMemberByOwner(campaignID, actor.Username); exists {
			ownCharacterID = m.CharacterID
		}
		playMembersMu.Unlock()
	}

	campaignWhispersMu.Lock()
	defer campaignWhispersMu.Unlock()

	whispers := make([]map[string]any, 0, len(campaignWhispers[campaignID]))
	for _, wh := range campaignWhispers[campaignID] {
		if isDM || (ownCharacterID != "" && (wh.FromCharacterID == ownCharacterID || wh.ToCharacterID == ownCharacterID)) {
			whispers = append(whispers, whisperJSON(wh))
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{"whispers": whispers})
}

// characterSheetHandler returns a character's basic sheet, readable only by
// the character owner and the campaign dm.
func characterSheetHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
	isDM, ok := requireCampaignAccess(w, c, actor)
	if !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	owner := playMemberOwner(member)
	if !isDM && actor.Username != owner {
		writeError(w, http.StatusForbidden, "only the character owner or campaign dm may view this sheet")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id":      member.CharacterID,
		"owner":             owner,
		"name":              member.Name,
		"class":             member.Class,
		"level":             1,
		"proficiency_bonus": 2,
		"hp_max":            10,
		"armor_class":       10,
	})
}
