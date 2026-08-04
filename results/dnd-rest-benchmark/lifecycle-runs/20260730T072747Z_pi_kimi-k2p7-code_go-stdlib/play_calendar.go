package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// calendarResponse is the exact shape returned for a campaign calendar. Weather
// is derived deterministically from the current day and season.
type calendarResponse struct {
	Day     int    `json:"day"`
	Season  string `json:"season"`
	Weather string `json:"weather"`
}

// initCalendarRequest binds the payload for initializing a campaign calendar.
type initCalendarRequest struct {
	Day    int    `json:"day"`
	Season string `json:"season"`
}

// advanceCalendarRequest binds the payload for advancing a campaign calendar.
type advanceCalendarRequest struct {
	Days int `json:"days"`
}

// seasonOffsets maps each valid season to its weather-cycle offset.
var seasonOffsets = map[string]int{
	"spring": 0,
	"summer": 1,
	"autumn": 2,
	"winter": 3,
}

// weatherByRemainder maps (day+season_offset)%4 to a deterministic weather kind.
var weatherByRemainder = []string{"clear", "rain", "wind", "snow"}

// computeWeather returns the deterministic weather for a given day and season.
func computeWeather(day int, season string) string {
	return weatherByRemainder[(day+seasonOffsets[season])%4]
}

// queryCalendar loads a campaign calendar by campaign id. The caller must hold
// dbMu.
func queryCalendar(campaignID string) (*calendarResponse, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT day, season FROM campaign_calendars WHERE campaign_id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		return nil, false, err
	}
	var rows []struct {
		Day    int    `json:"day"`
		Season string `json:"season"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &calendarResponse{
		Day:     rows[0].Day,
		Season:  rows[0].Season,
		Weather: computeWeather(rows[0].Day, rows[0].Season),
	}, true, nil
}

// createCalendarHandler initializes the campaign calendar. Only the campaign
// owner (who must be a DM) may call it. Players and non-owner DMs receive 403;
// invalid payloads return 400; an already initialized calendar returns 409;
// an unknown campaign returns 404.
func createCalendarHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("calendar create campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req initCalendarRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if _, validSeason := seasonOffsets[req.Season]; !validSeason || req.Day < 1 {
		writeError(w, http.StatusBadRequest, "invalid calendar")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_calendars WHERE campaign_id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		log.Printf("calendar exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "calendar already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_calendars (campaign_id, day, season) VALUES (%s, %d, %s);",
		sq(campaignID), req.Day, sq(req.Season))); err != nil {
		log.Printf("calendar insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, calendarResponse{
		Day:     req.Day,
		Season:  req.Season,
		Weather: computeWeather(req.Day, req.Season),
	})
}

// getCalendarHandler returns the campaign calendar. It is available to the
// campaign owner and all joined members. If the calendar has not been
// initialized, it returns 404.
func getCalendarHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	calendar, ok, err := queryCalendar(campaignID)
	if err != nil {
		log.Printf("calendar get query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "calendar not found")
		return
	}

	writeJSON(w, http.StatusOK, calendar)
}

// advanceCalendarHandler advances the campaign calendar by a bounded number of
// days. Only the campaign owner may call it. Players and non-owner DMs receive
// 403; days must be an integer from 1 through 30; advancing a noninitialized
// calendar returns 404.
func advanceCalendarHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("calendar advance campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req advanceCalendarRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Days < 1 || req.Days > 30 {
		writeError(w, http.StatusBadRequest, "invalid advance")
		return
	}

	calendar, ok, err := queryCalendar(campaignID)
	if err != nil {
		log.Printf("calendar advance query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "calendar not found")
		return
	}

	newDay := calendar.Day + req.Days
	if err := dbExec(fmt.Sprintf("UPDATE campaign_calendars SET day=%d WHERE campaign_id=%s;",
		newDay, sq(campaignID))); err != nil {
		log.Printf("calendar advance update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, calendarResponse{
		Day:     newDay,
		Season:  calendar.Season,
		Weather: computeWeather(newDay, calendar.Season),
	})
}
