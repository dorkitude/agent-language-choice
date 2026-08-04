package main

import (
	"encoding/json"
	"net/http"
)

// playCalendar is a campaign's day/season calendar, initialized once by the
// dm and advanced in bounded day increments.
type playCalendar struct {
	Day    int
	Season string
}

// seasonOffsets maps each valid season to its weather-computation offset.
var seasonOffsets = map[string]int{
	"spring": 0,
	"summer": 1,
	"autumn": 2,
	"winter": 3,
}

var weatherByIndex = []string{"clear", "rain", "wind", "snow"}

// playCalendarWeather derives the deterministic weather for a day/season.
func playCalendarWeather(day int, season string) string {
	idx := (day + seasonOffsets[season]) % 4
	return weatherByIndex[idx]
}

func playCalendarResponse(cal *playCalendar) map[string]interface{} {
	return map[string]interface{}{
		"day":     cal.Day,
		"season":  cal.Season,
		"weather": playCalendarWeather(cal.Day, cal.Season),
	}
}

// handlePlayCampaignCalendarSub routes the "calendar" and "calendar/advance"
// sub-paths of a play campaign. It returns false if rest does not name a
// calendar path, so the caller can fall through to its own routing.
func handlePlayCampaignCalendarSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "calendar" {
		switch r.Method {
		case http.MethodPost:
			handleInitPlayCalendar(w, r, campaignID)
		case http.MethodGet:
			handleGetPlayCalendar(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if rest == "calendar/advance" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleAdvancePlayCalendar(w, r, campaignID)
		return true
	}
	return false
}

// handleInitPlayCalendar lets the campaign dm initialize the calendar once.
func handleInitPlayCalendar(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Day    *int   `json:"day"`
		Season string `json:"season"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Day == nil || *req.Day < 1 {
		writeError(w, http.StatusBadRequest, "day must be an integer greater than or equal to 1")
		return
	}
	if _, validSeason := seasonOffsets[req.Season]; !validSeason {
		writeError(w, http.StatusBadRequest, "season must be one of spring, summer, autumn, or winter")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may initialize the calendar")
		return
	}
	if c.Calendar != nil {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "calendar is already initialized")
		return
	}

	c.Calendar = &playCalendar{Day: *req.Day, Season: req.Season}
	resp := playCalendarResponse(c.Calendar)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleGetPlayCalendar returns the campaign calendar to any authenticated
// campaign member.
func handleGetPlayCalendar(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the owner or a member may view the calendar")
		return
	}
	if c.Calendar == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "calendar has not been initialized")
		return
	}
	resp := playCalendarResponse(c.Calendar)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handleAdvancePlayCalendar lets the campaign dm advance the calendar by a
// bounded number of days.
func handleAdvancePlayCalendar(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Days *int `json:"days"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Days == nil || *req.Days < 1 || *req.Days > 30 {
		writeError(w, http.StatusBadRequest, "days must be an integer from 1 through 30")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may advance the calendar")
		return
	}
	if c.Calendar == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "calendar has not been initialized")
		return
	}

	c.Calendar.Day += *req.Days
	resp := playCalendarResponse(c.Calendar)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}
