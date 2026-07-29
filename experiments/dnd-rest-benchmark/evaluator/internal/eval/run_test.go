package eval

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"testing"
	"time"
)

func TestSuitesPassReferenceServer(t *testing.T) {
	for _, suite := range Suites() {
		server := httptest.NewServer(ReferenceHandler())
		report, err := Run(context.Background(), RunConfig{
			BaseURL: server.URL,
			Suite:   suite.ID,
			Timeout: time.Second,
		})
		server.Close()
		if err != nil {
			t.Fatalf("Run(%s) returned error: %v", suite.ID, err)
		}
		if !report.Passed {
			payload, _ := json.MarshalIndent(report, "", "  ")
			t.Fatalf("reference server failed suite %s:\n%s", suite.ID, payload)
		}
	}
}
