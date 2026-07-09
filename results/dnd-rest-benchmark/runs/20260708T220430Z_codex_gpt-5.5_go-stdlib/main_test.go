package main

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHandlers(t *testing.T) {
	tests := []struct {
		name   string
		method string
		path   string
		body   string
		want   string
	}{
		{
			name:   "health",
			method: http.MethodGet,
			path:   "/health",
			want:   `{"ok":true}` + "\n",
		},
		{
			name:   "dice stats",
			method: http.MethodPost,
			path:   "/v1/dice/stats",
			body:   `{"expression":"2d6+3"}`,
			want:   `{"dice_count":2,"sides":6,"modifier":3,"min":5,"max":15,"average":10}` + "\n",
		},
		{
			name:   "ability check",
			method: http.MethodPost,
			path:   "/v1/checks/ability",
			body:   `{"roll":9,"modifier":5,"dc":15}`,
			want:   `{"total":14,"success":false,"margin":-1}` + "\n",
		},
		{
			name:   "adjusted xp",
			method: http.MethodPost,
			path:   "/v1/encounters/adjusted-xp",
			body:   `{"party":[{"level":3},{"level":3},{"level":3},{"level":3}],"monsters":[{"cr":"1","count":2},{"cr":"2","count":1}]}`,
			want:   `{"base_xp":850,"monster_count":3,"multiplier":2,"adjusted_xp":1700,"difficulty":"deadly","thresholds":{"easy":300,"medium":600,"hard":900,"deadly":1600}}` + "\n",
		},
		{
			name:   "initiative order",
			method: http.MethodPost,
			path:   "/v1/initiative/order",
			body:   `{"combatants":[{"name":"rogue","dex":3,"roll":14},{"name":"ogre","dex":-1,"roll":16}]}`,
			want:   `{"order":[{"name":"rogue","score":17},{"name":"ogre","score":15}]}` + "\n",
		},
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("/v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("/v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("/v1/initiative/order", initiativeOrderHandler)

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(tt.method, tt.path, bytes.NewBufferString(tt.body))
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, req)

			if rec.Code != http.StatusOK {
				t.Fatalf("status = %d, want %d; body %s", rec.Code, http.StatusOK, rec.Body.String())
			}
			if rec.Body.String() != tt.want {
				t.Fatalf("body = %q, want %q", rec.Body.String(), tt.want)
			}
		})
	}
}

func TestInvalidDiceExpression(t *testing.T) {
	req := httptest.NewRequest(http.MethodPost, "/v1/dice/stats", bytes.NewBufferString(`{"expression":"0d6"}`))
	rec := httptest.NewRecorder()

	diceStatsHandler(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusBadRequest)
	}
}
