package main

import (
	"fmt"
	"net/http"
	"sync"
)

// campaignBackup is one immutable DM-only campaign backup snapshot.
type campaignBackup struct {
	CampaignID string
	Sequence   int
	BackupID   string
	Story      string
	Status     string
}

// campaignBackupsMu guards campaignBackups, the in-memory index mirroring the
// play_campaign_backups table. Keyed by campaign id, holding backups in
// creation order starting at backup-1.
var (
	campaignBackupsMu sync.Mutex
	campaignBackups   = map[string][]*campaignBackup{}
)

func backupJSON(b *campaignBackup) map[string]any {
	return map[string]any{
		"backup_id": b.BackupID,
		"story":     b.Story,
		"status":    b.Status,
	}
}

// createBackupHandler lets only the campaign DM snapshot the campaign's
// current public story and status into a new immutable, sequential backup.
func createBackupHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
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
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may create backups")
		return
	}

	campaignBackupsMu.Lock()
	defer campaignBackupsMu.Unlock()

	seq := len(campaignBackups[campaignID]) + 1
	entry := &campaignBackup{
		CampaignID: campaignID,
		Sequence:   seq,
		BackupID:   fmt.Sprintf("backup-%d", seq),
		Story:      c.Story,
		Status:     c.Status,
	}
	if err := saveCampaignBackupToDB(entry); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save backup")
		return
	}
	campaignBackups[campaignID] = append(campaignBackups[campaignID], entry)

	writeJSON(w, http.StatusCreated, backupJSON(entry))
}

// listBackupsHandler lets only the campaign DM list the campaign's backups in
// creation order.
func listBackupsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may list backups")
		return
	}

	campaignBackupsMu.Lock()
	defer campaignBackupsMu.Unlock()

	backups := make([]map[string]any, 0, len(campaignBackups[campaignID]))
	for _, b := range campaignBackups[campaignID] {
		backups = append(backups, backupJSON(b))
	}

	writeJSON(w, http.StatusOK, map[string]any{"backups": backups})
}

// restoreBackupHandler lets only the campaign DM restore an existing backup
// snapshot's story and status onto the campaign, without mutating the
// snapshot itself or creating a new backup.
func restoreBackupHandler(w http.ResponseWriter, r *http.Request, campaignID string, backupID string) {
	if !requireMethod(w, r, http.MethodPost) {
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
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may restore backups")
		return
	}

	campaignBackupsMu.Lock()
	defer campaignBackupsMu.Unlock()

	var found *campaignBackup
	for _, b := range campaignBackups[campaignID] {
		if b.BackupID == backupID {
			found = b
			break
		}
	}
	if found == nil {
		writeError(w, http.StatusNotFound, "backup not found")
		return
	}

	c.Story = found.Story
	c.Status = found.Status
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	writeJSON(w, http.StatusOK, backupJSON(found))
}
