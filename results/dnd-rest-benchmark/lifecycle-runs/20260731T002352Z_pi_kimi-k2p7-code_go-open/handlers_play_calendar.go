package main

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createCalendarHandler initializes the campaign calendar.
// Only the campaign owner (DM) may initialize it. Players receive 403.
// Duplicate initialization for the same campaign returns 409.
func createCalendarHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can initialize the calendar")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can initialize the calendar")
		return
	}

	var req calendarCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Day < 1 {
		badRequest(w, "day must be an integer greater than or equal to 1")
		return
	}
	season := strings.ToLower(strings.TrimSpace(req.Season))
	if _, ok := seasonOffsets[season]; !ok {
		badRequest(w, "season must be one of spring, summer, autumn, or winter")
		return
	}

	if err := dbCreateCalendar(id, req.Day, season); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "calendar already initialized")
			return
		}
		log.Printf("create calendar: %v", err)
		badRequest(w, "failed to create calendar")
		return
	}

	writeJSON(w, http.StatusCreated, calendarResponse{
		Day:     req.Day,
		Season:  season,
		Weather: computeWeather(req.Day, season),
	})
}

// getCalendarHandler reads the campaign calendar for any authenticated member.
// If the calendar has not been initialized, it returns 404.
func getCalendarHandler(w http.ResponseWriter, r *http.Request) {
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

	cal, err := dbGetCalendar(id)
	if err != nil {
		log.Printf("get calendar: %v", err)
		badRequest(w, "failed to read calendar")
		return
	}
	if cal == nil {
		notFound(w, "calendar not found")
		return
	}

	writeJSON(w, http.StatusOK, cal)
}

// advanceCalendarHandler advances the campaign calendar by a bounded number of
// days. Only the campaign owner (DM) may advance the calendar. Players receive
// 403. Advancing a non-initialized calendar returns 404.
func advanceCalendarHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can advance the calendar")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can advance the calendar")
		return
	}

	var req calendarAdvanceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Days < 1 || req.Days > 30 {
		badRequest(w, "days must be an integer from 1 through 30")
		return
	}

	cal, err := dbAdvanceCalendar(id, req.Days)
	if err != nil {
		if err == sql.ErrNoRows {
			notFound(w, "calendar not found")
			return
		}
		log.Printf("advance calendar: %v", err)
		badRequest(w, "failed to advance calendar")
		return
	}

	writeJSON(w, http.StatusOK, cal)
}
