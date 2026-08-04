package main

import (
	"net/http"
	"sync"
)

// playCalendar is the deterministic campaign calendar: a current day and
// season from which weather is derived.
type playCalendar struct {
	CampaignID string
	Day        int
	Season     string
}

// calendarsMu guards calendars, the in-memory index mirroring the
// play_calendars table. Keyed by campaign id.
var (
	calendarsMu sync.Mutex
	calendars   = map[string]*playCalendar{}
)

var seasonOffsets = map[string]int{
	"spring": 0,
	"summer": 1,
	"autumn": 2,
	"winter": 3,
}

var weatherByOffset = map[int]string{
	0: "clear",
	1: "rain",
	2: "wind",
	3: "snow",
}

func calendarWeather(day int, season string) string {
	offset := seasonOffsets[season]
	return weatherByOffset[((day+offset)%4+4)%4]
}

func calendarJSON(c *playCalendar) map[string]any {
	return map[string]any{
		"day":     c.Day,
		"season":  c.Season,
		"weather": calendarWeather(c.Day, c.Season),
	}
}

func isValidSeason(season string) bool {
	_, ok := seasonOffsets[season]
	return ok
}

type initCalendarRequest struct {
	Day    int    `json:"day"`
	Season string `json:"season"`
}

// initCalendarHandler lets the campaign's owning dm initialize the campaign
// calendar exactly once.
func initCalendarHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req initCalendarRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may initialize the calendar")
		return
	}

	if req.Day < 1 || !isValidSeason(req.Season) {
		writeError(w, http.StatusBadRequest, "day must be an integer >= 1 and season must be one of spring, summer, autumn, winter")
		return
	}

	calendarsMu.Lock()
	defer calendarsMu.Unlock()

	if _, exists := calendars[campaignID]; exists {
		writeError(w, http.StatusConflict, "calendar already initialized for this campaign")
		return
	}

	cal := &playCalendar{CampaignID: campaignID, Day: req.Day, Season: req.Season}
	if err := saveCalendarToDB(cal); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save calendar")
		return
	}
	calendars[campaignID] = cal

	writeJSON(w, http.StatusCreated, calendarJSON(cal))
}

// getCalendarHandler returns a campaign's calendar to any authenticated
// campaign member, including the dm and joined players.
func getCalendarHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	calendarsMu.Lock()
	defer calendarsMu.Unlock()

	cal, exists := calendars[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "calendar has not been initialized for this campaign")
		return
	}

	writeJSON(w, http.StatusOK, calendarJSON(cal))
}

type advanceCalendarRequest struct {
	Days int `json:"days"`
}

// advanceCalendarHandler lets the campaign's owning dm advance an already
// initialized calendar by a bounded number of days.
func advanceCalendarHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req advanceCalendarRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may advance the calendar")
		return
	}

	if req.Days < 1 || req.Days > 30 {
		writeError(w, http.StatusBadRequest, "days must be an integer from 1 through 30")
		return
	}

	calendarsMu.Lock()
	defer calendarsMu.Unlock()

	cal, exists := calendars[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "calendar has not been initialized for this campaign")
		return
	}

	cal.Day += req.Days
	if err := saveCalendarToDB(cal); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save calendar")
		return
	}

	writeJSON(w, http.StatusOK, calendarJSON(cal))
}
