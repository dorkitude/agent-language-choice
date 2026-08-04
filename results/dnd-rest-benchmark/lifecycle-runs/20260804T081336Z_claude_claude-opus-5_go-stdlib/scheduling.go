package main

import (
	"encoding/json"
	"net/http"
	"sort"
	"time"
)

// Campaign session scheduling: a campaign owns an ordered list of scheduled
// play sessions, each with a start instant, a duration, an agenda, and an
// attendance record.
//
// Start times arrive as RFC 3339 strings. The parsed instant is kept alongside
// the original text so ordering can compare instants (making offsets like
// +02:00 sort correctly against Z) while responses echo the caller's spelling
// verbatim.
//
// "Next" means the earliest scheduled session, not the earliest one still in
// the future: the service has no notion of "now" that a client can rely on, and
// a wall-clock comparison would make the endpoint's answer drift over time.
// Ties fall back to insertion order.
//
// Attendance is a replace, not an accumulate — re-recording a session's roster
// overwrites the previous lists, so a corrected roster is expressible and a
// replayed call is idempotent.
//
// Like the rest of the campaign state, sessions live under campaigns.mu and are
// mirrored to SQLite by flush().

type campaignSession struct {
	ID              string
	StartsAt        string    // original RFC 3339 text, echoed back to clients
	StartsAtTime    time.Time // parsed instant, used only for ordering
	DurationMinutes int
	Agenda          []string
	Present         []string
	Absent          []string
}

// findCampaignSession returns the campaign's session with the given id.
// Callers must hold campaigns.mu.
func findCampaignSession(c *campaign, id string) *campaignSession {
	for _, s := range c.Sessions {
		if s.ID == id {
			return s
		}
	}
	return nil
}

// nextCampaignSession returns the earliest scheduled session, or nil when none
// are scheduled. Callers must hold campaigns.mu.
func nextCampaignSession(c *campaign) *campaignSession {
	ordered := append([]*campaignSession{}, c.Sessions...)
	sort.SliceStable(ordered, func(i, j int) bool {
		return ordered[i].StartsAtTime.Before(ordered[j].StartsAtTime)
	})
	if len(ordered) == 0 {
		return nil
	}
	return ordered[0]
}

// ---------- request / response payloads ----------

type scheduleSessionRequest struct {
	ID              *string          `json:"id"`
	StartsAt        *string          `json:"starts_at"`
	DurationMinutes *json.RawMessage `json:"duration_minutes"`
	Agenda          *[]string        `json:"agenda"`
}

type scheduleSessionResponse struct {
	ID              string `json:"id"`
	StartsAt        string `json:"starts_at"`
	DurationMinutes int    `json:"duration_minutes"`
	AgendaCount     int    `json:"agenda_count"`
}

type attendanceRequest struct {
	Present *[]string `json:"present"`
	Absent  *[]string `json:"absent"`
}

type attendanceResponse struct {
	SessionID    string `json:"session_id"`
	PresentCount int    `json:"present_count"`
	AbsentCount  int    `json:"absent_count"`
}

type nextSessionResponse struct {
	ID          string `json:"id"`
	StartsAt    string `json:"starts_at"`
	AgendaCount int    `json:"agenda_count"`
}

// ---------- POST /v1/campaigns/{id}/sessions ----------

func handleScheduleSession(w http.ResponseWriter, r *http.Request) {
	var req scheduleSessionRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	id, ok := requiredString(req.ID)
	if !ok {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	startsAt, ok := requiredString(req.StartsAt)
	if !ok {
		writeError(w, http.StatusBadRequest, "starts_at is required")
		return
	}
	startsAtTime, err := time.Parse(time.RFC3339, startsAt)
	if err != nil {
		writeError(w, http.StatusBadRequest, "starts_at must be an RFC 3339 timestamp")
		return
	}
	duration, ok := asInt(req.DurationMinutes)
	if !ok || duration < 1 {
		writeError(w, http.StatusBadRequest, "duration_minutes must be a positive integer")
		return
	}
	// An omitted agenda simply means an empty one; a supplied agenda must be a
	// list of strings, which the decoder has already enforced.
	agenda := []string{}
	if req.Agenda != nil {
		agenda = append(agenda, *req.Agenda...)
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if findCampaignSession(c, id) != nil {
		campaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "session id already exists")
		return
	}
	s := &campaignSession{
		ID:              id,
		StartsAt:        startsAt,
		StartsAtTime:    startsAtTime,
		DurationMinutes: duration,
		Agenda:          agenda,
		Present:         []string{},
		Absent:          []string{},
	}
	c.Sessions = append(c.Sessions, s)
	resp := scheduleSessionResponse{
		ID:              s.ID,
		StartsAt:        s.StartsAt,
		DurationMinutes: s.DurationMinutes,
		AgendaCount:     len(s.Agenda),
	}
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, resp)
}

// ---------- POST /v1/campaigns/{id}/sessions/{session_id}/attendance ----------

func handleSessionAttendance(w http.ResponseWriter, r *http.Request) {
	var req attendanceRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	present := []string{}
	if req.Present != nil {
		present = append(present, *req.Present...)
	}
	absent := []string{}
	if req.Absent != nil {
		absent = append(absent, *req.Absent...)
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	s := findCampaignSession(c, r.PathValue("session_id"))
	if s == nil {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "session not found")
		return
	}
	s.Present = present
	s.Absent = absent
	resp := attendanceResponse{
		SessionID:    s.ID,
		PresentCount: len(s.Present),
		AbsentCount:  len(s.Absent),
	}
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusOK, resp)
}

// ---------- GET /v1/campaigns/{id}/sessions/next ----------

func handleNextSession(w http.ResponseWriter, r *http.Request) {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	s := nextCampaignSession(c)
	if s == nil {
		writeError(w, http.StatusNotFound, "no scheduled sessions")
		return
	}
	writeJSON(w, http.StatusOK, nextSessionResponse{
		ID:          s.ID,
		StartsAt:    s.StartsAt,
		AgendaCount: len(s.Agenda),
	})
}

// ---------- persistence helpers ----------

// sessionRows renders one campaign's scheduled sessions as storage rows. The
// agenda and attendance lists are JSON-encoded because the writer only handles
// flat columns. Callers must hold campaigns.mu.
func sessionRows(c *campaign) [][]any {
	out := make([][]any, 0, len(c.Sessions))
	for i, s := range c.Sessions {
		agenda, _ := json.Marshal(s.Agenda)
		present, _ := json.Marshal(s.Present)
		absent, _ := json.Marshal(s.Absent)
		out = append(out, []any{
			c.ID, s.ID, s.StartsAt, int64(s.DurationMinutes),
			string(agenda), string(present), string(absent), int64(i),
		})
	}
	return out
}

// sessionFromRow rebuilds a scheduled session from a storage row, returning the
// owning campaign id. A row whose start time no longer parses is rejected,
// since ordering depends on it.
func sessionFromRow(row []any) (campaignID string, s *campaignSession, ok bool) {
	if len(row) < 8 {
		return "", nil, false
	}
	campaignID, _ = row[0].(string)
	id, _ := row[1].(string)
	startsAt, _ := row[2].(string)
	duration, _ := row[3].(int64)
	agendaJSON, _ := row[4].(string)
	presentJSON, _ := row[5].(string)
	absentJSON, _ := row[6].(string)
	if campaignID == "" || id == "" {
		return "", nil, false
	}
	startsAtTime, err := time.Parse(time.RFC3339, startsAt)
	if err != nil {
		return "", nil, false
	}
	// The lists must stay JSON arrays, never null, in responses and snapshots.
	agenda, present, absent := []string{}, []string{}, []string{}
	_ = json.Unmarshal([]byte(agendaJSON), &agenda)
	_ = json.Unmarshal([]byte(presentJSON), &present)
	_ = json.Unmarshal([]byte(absentJSON), &absent)
	return campaignID, &campaignSession{
		ID:              id,
		StartsAt:        startsAt,
		StartsAtTime:    startsAtTime,
		DurationMinutes: int(duration),
		Agenda:          agenda,
		Present:         present,
		Absent:          absent,
	}, true
}
