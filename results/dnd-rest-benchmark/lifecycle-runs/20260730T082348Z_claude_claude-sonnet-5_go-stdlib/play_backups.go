package main

import (
	"fmt"
	"net/http"
	"strings"
)

// playBackup is an immutable snapshot of a campaign's public story and
// status, taken at the moment the backup was created.
type playBackup struct {
	BackupID string
	Story    string
	Status   string
}

func playBackupResponse(b *playBackup) map[string]interface{} {
	return map[string]interface{}{
		"backup_id": b.BackupID,
		"story":     b.Story,
		"status":    b.Status,
	}
}

// findPlayBackup locates a backup by id within c.
func findPlayBackup(c *playCampaign, backupID string) *playBackup {
	for _, b := range c.Backups {
		if b.BackupID == backupID {
			return b
		}
	}
	return nil
}

// handlePlayCampaignBackupsSub routes the "backups" and
// "backups/{backup_id}/restore" sub-paths of a play campaign. It returns
// false if rest does not name a backups path, so the caller can fall through
// to its own routing.
func handlePlayCampaignBackupsSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "backups" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayBackup(w, r, campaignID)
		case http.MethodGet:
			handleListPlayBackups(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if !strings.HasPrefix(rest, "backups/") {
		return false
	}
	backupRest := strings.TrimPrefix(rest, "backups/")
	if backupID, ok := strings.CutSuffix(backupRest, "/restore"); ok && backupID != "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleRestorePlayBackup(w, r, campaignID, backupID)
		return true
	}
	return false
}

// handleCreatePlayBackup lets the campaign dm snapshot the campaign's
// current public story and status as a new immutable backup.
func handleCreatePlayBackup(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the campaign dm may create a backup")
		return
	}

	c.BackupSeq++
	b := &playBackup{
		BackupID: fmt.Sprintf("backup-%d", c.BackupSeq),
		Story:    c.Story,
		Status:   c.Status,
	}
	c.Backups = append(c.Backups, b)
	resp := playBackupResponse(b)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleListPlayBackups returns every campaign backup, in creation order, to
// the campaign dm only.
func handleListPlayBackups(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the campaign dm may list backups")
		return
	}

	backups := make([]map[string]interface{}, 0, len(c.Backups))
	for _, b := range c.Backups {
		backups = append(backups, playBackupResponse(b))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"backups": backups,
	})
}

// handleRestorePlayBackup lets the campaign dm apply an existing backup's
// story and status to the campaign, without mutating the backup itself or
// creating a new snapshot.
func handleRestorePlayBackup(w http.ResponseWriter, r *http.Request, campaignID, backupID string) {
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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the campaign dm may restore a backup")
		return
	}
	b := findPlayBackup(c, backupID)
	if b == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "backup not found")
		return
	}

	c.Story = b.Story
	c.Status = b.Status
	resp := playBackupResponse(b)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}
