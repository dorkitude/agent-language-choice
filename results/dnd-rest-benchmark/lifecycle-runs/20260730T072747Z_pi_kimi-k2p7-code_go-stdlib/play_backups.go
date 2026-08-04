package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// campaignBackup is the immutable snapshot of a campaign's public story and
// status at the moment the backup was created.
type campaignBackup struct {
	BackupID string `json:"backup_id"`
	Story    string `json:"story"`
	Status   string `json:"status"`
}

// campaignBackupListResponse is the exact shape returned by the list backups
// endpoint.
type campaignBackupListResponse struct {
	Backups []campaignBackup `json:"backups"`
}

// queryCampaignBackups loads all backups for a campaign ordered by creation
// sequence. The caller must hold dbMu.
func queryCampaignBackups(campaignID string) ([]campaignBackup, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT backup_id, story, status FROM campaign_backups WHERE campaign_id=%s ORDER BY sequence;", sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var backups []campaignBackup
	if err := json.Unmarshal(out, &backups); err != nil {
		return nil, err
	}
	if backups == nil {
		backups = []campaignBackup{}
	}
	return backups, nil
}

// queryCampaignBackup loads a single backup by campaign and backup id. The
// caller must hold dbMu.
func queryCampaignBackup(campaignID, backupID string) (*campaignBackup, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT backup_id, story, status FROM campaign_backups WHERE campaign_id=%s AND backup_id=%s LIMIT 1;", sq(campaignID), sq(backupID)))
	if err != nil {
		return nil, false, err
	}
	var backups []campaignBackup
	if err := json.Unmarshal(out, &backups); err != nil {
		return nil, false, err
	}
	if len(backups) == 0 {
		return nil, false, nil
	}
	return &backups[0], true, nil
}

// nextBackupSequence returns the next monotonic sequence number for a
// campaign's backups. The caller must hold dbMu.
func nextBackupSequence(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_backups WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextSeq, nil
}

// queryCampaignDocumentStory returns the current public story for a campaign,
// defaulting to the empty string when no document row exists yet. The caller
// must hold dbMu.
func queryCampaignDocumentStory(campaignID string) (string, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT story FROM campaign_documents WHERE campaign_id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		return "", err
	}
	var docs []struct {
		Story string `json:"story"`
	}
	if err := json.Unmarshal(out, &docs); err != nil {
		return "", err
	}
	if len(docs) == 0 {
		return "", nil
	}
	return docs[0].Story, nil
}

// createCampaignBackupHandler creates a new immutable backup snapshot of the
// campaign's current public story and status. Only the campaign owner may
// call this endpoint.
func createCampaignBackupHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("backup create campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	story, err := queryCampaignDocumentStory(campaignID)
	if err != nil {
		log.Printf("backup create story query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	seq, err := nextBackupSequence(campaignID)
	if err != nil {
		log.Printf("backup create sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	backupID := fmt.Sprintf("backup-%d", seq)

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_backups (campaign_id, backup_id, sequence, story, status) VALUES (%s, %s, %d, %s, %s);",
		sq(campaignID), sq(backupID), seq, sq(story), sq(campaign.Status))); err != nil {
		log.Printf("backup create insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, campaignBackup{
		BackupID: backupID,
		Story:    story,
		Status:   campaign.Status,
	})
}

// listCampaignBackupsHandler returns all immutable backup snapshots for a
// campaign in creation order. Only the campaign owner may call this endpoint.
func listCampaignBackupsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	backups, err := queryCampaignBackups(campaignID)
	if err != nil {
		log.Printf("backup list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, campaignBackupListResponse{Backups: backups})
}

// restoreCampaignBackupHandler applies a snapshot's story and status to the
// campaign without mutating the snapshot itself or creating a new backup.
// Only the campaign owner may call this endpoint.
func restoreCampaignBackupHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	backupID := r.PathValue("backup_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	backup, ok, err := queryCampaignBackup(campaignID, backupID)
	if err != nil {
		log.Printf("backup restore query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "backup not found")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET status=%s WHERE id=%s;",
		sq(backup.Status), sq(campaignID))); err != nil {
		log.Printf("backup restore status update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_documents (campaign_id, story, dm_notes) VALUES (%s, %s, '') ON CONFLICT(campaign_id) DO UPDATE SET story=excluded.story;",
		sq(campaignID), sq(backup.Story))); err != nil {
		log.Printf("backup restore story update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, campaignBackup{
		BackupID: backup.BackupID,
		Story:    backup.Story,
		Status:   backup.Status,
	})
}
