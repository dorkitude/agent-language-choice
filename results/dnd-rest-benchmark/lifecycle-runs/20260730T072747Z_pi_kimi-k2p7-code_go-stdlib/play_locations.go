package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

type campaignLocation struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// locationConnection is a directed edge between two locations in a campaign.
type locationConnection struct {
	FromID      string `json:"from_id"`
	ToID        string `json:"to_id"`
	TravelTurns int    `json:"travel_turns"`
}

// travelDestination is a destination exposed on the travel endpoint.
type travelDestination struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	TravelTurns int    `json:"travel_turns"`
}

// travelResponse is the shape returned by the valid travel endpoint.
type travelResponse struct {
	Destinations []travelDestination `json:"destinations"`
}

// queryCampaignLocation loads a location by id within a campaign. The caller
// must hold dbMu.
func queryCampaignLocation(campaignID, locationID string) (*campaignLocation, bool, error) {
	var locations []campaignLocation
	if err := queryRows(fmt.Sprintf("SELECT id, name FROM campaign_locations WHERE id=%s AND campaign_id=%s LIMIT 1;", sq(locationID), sq(campaignID)), &locations); err != nil {
		return nil, false, err
	}
	if len(locations) == 0 {
		return nil, false, nil
	}
	return &locations[0], true, nil
}

// createLocationRequest binds the payload for a new campaign location.
type createLocationRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// createLocationHandler lets the campaign owner create a new location in the
// campaign's deterministic location graph. Duplicate ids return 409.
func createLocationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createLocationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "invalid location")
		return
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_locations WHERE id=%s AND campaign_id=%s LIMIT 1;", sq(req.ID), sq(campaignID)))
	if err != nil {
		log.Printf("location exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "location already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_locations (id, campaign_id, name) VALUES (%s, %s, %s);",
		sq(req.ID), sq(campaignID), sq(req.Name))); err != nil {
		log.Printf("location insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, campaignLocation{
		ID:   req.ID,
		Name: req.Name,
	})
}

// createConnectionRequest binds the payload for a new location connection.
type createConnectionRequest struct {
	ToID        string `json:"to_id"`
	TravelTurns int    `json:"travel_turns"`
}

// createConnectionHandler lets the campaign owner create a directed connection
// from one location to another. Connections to missing locations or already
// connected destinations are rejected with 400.
func createConnectionHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	fromID := r.PathValue("from_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createConnectionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ToID == "" || req.TravelTurns < 1 {
		writeError(w, http.StatusBadRequest, "invalid connection")
		return
	}

	if _, ok, err := queryCampaignLocation(campaignID, fromID); err != nil {
		log.Printf("connection from location query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusBadRequest, "invalid connection")
		return
	}

	if _, ok, err := queryCampaignLocation(campaignID, req.ToID); err != nil {
		log.Printf("connection to location query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusBadRequest, "invalid connection")
		return
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM location_connections WHERE campaign_id=%s AND from_id=%s AND to_id=%s LIMIT 1;",
		sq(campaignID), sq(fromID), sq(req.ToID)))
	if err != nil {
		log.Printf("connection exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusBadRequest, "invalid connection")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (%s, %s, %s, %d);",
		sq(campaignID), sq(fromID), sq(req.ToID), req.TravelTurns)); err != nil {
		log.Printf("connection insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, locationConnection{
		FromID:      fromID,
		ToID:        req.ToID,
		TravelTurns: req.TravelTurns,
	})
}

// getValidTravelHandler returns the valid outbound destinations from a
// location for any campaign owner or member. Each destination includes the
// connected location's name and travel cost.
func getValidTravelHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	locationID := r.PathValue("loc_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	if _, ok, err := queryCampaignLocation(campaignID, locationID); err != nil {
		log.Printf("travel location query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "location not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT l.id, l.name, c.travel_turns FROM location_connections c JOIN campaign_locations l ON c.to_id=l.id AND c.campaign_id=l.campaign_id WHERE c.campaign_id=%s AND c.from_id=%s ORDER BY l.id;",
		sq(campaignID), sq(locationID)))
	if err != nil {
		log.Printf("travel connections query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var destinations []travelDestination
	if err := json.Unmarshal(out, &destinations); err != nil {
		log.Printf("travel connections unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if destinations == nil {
		destinations = []travelDestination{}
	}

	writeJSON(w, http.StatusOK, travelResponse{
		Destinations: destinations,
	})
}
