package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
)

// campaignExport is an immutable snapshot of a campaign's public story and
// status at the time the export was created.
type campaignExport struct {
	Version int    `json:"version"`
	Story   string `json:"story"`
	Status  string `json:"status"`
}

// campaignExportsListResponse is the exact shape returned when listing exports.
type campaignExportsListResponse struct {
	Exports []campaignExport `json:"exports"`
}

// createCampaignExportHandler creates a new immutable export snapshot for the
// campaign. Only the campaign owner (DM) may call it. The version is one
// greater than the campaign's previous export count.
func createPlayCampaignExportHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("export campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT story FROM campaign_documents WHERE campaign_id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		log.Printf("export document query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var docs []struct {
		Story string `json:"story"`
	}
	if err := json.Unmarshal(out, &docs); err != nil {
		log.Printf("export document unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	story := ""
	if len(docs) > 0 {
		story = docs[0].Story
	}

	out, err = dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM campaign_exports WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		log.Printf("export next version query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		NextVersion int `json:"next_version"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("export next version unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	version := 1
	if len(rows) > 0 {
		version = rows[0].NextVersion
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_exports (campaign_id, version, story, status) VALUES (%s, %d, %s, %s);",
		sq(campaignID), version, sq(story), sq(campaign.Status))); err != nil {
		log.Printf("export insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, campaignExport{
		Version: version,
		Story:   story,
		Status:  campaign.Status,
	})
}

// listCampaignExportsHandler returns all export snapshots for the campaign in
// ascending version order. Only the campaign owner (DM) may call it.
func listPlayCampaignExportsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var exports []campaignExport
	if err := queryRows(fmt.Sprintf("SELECT version, story, status FROM campaign_exports WHERE campaign_id=%s ORDER BY version;", sq(campaignID)), &exports); err != nil {
		log.Printf("export list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exports == nil {
		exports = []campaignExport{}
	}

	writeJSON(w, http.StatusOK, campaignExportsListResponse{Exports: exports})
}

// getCampaignExportHandler returns a single export snapshot by version. Only
// the campaign owner (DM) may call it. Unknown versions return 404.
func getPlayCampaignExportHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	versionStr := r.PathValue("version")
	version, err := strconv.Atoi(versionStr)
	if err != nil || version < 1 {
		writeError(w, http.StatusNotFound, "export not found")
		return
	}

	var exports []campaignExport
	if err := queryRows(fmt.Sprintf("SELECT version, story, status FROM campaign_exports WHERE campaign_id=%s AND version=%d LIMIT 1;", sq(campaignID), version), &exports); err != nil {
		log.Printf("export get query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(exports) == 0 {
		writeError(w, http.StatusNotFound, "export not found")
		return
	}

	writeJSON(w, http.StatusOK, exports[0])
}
