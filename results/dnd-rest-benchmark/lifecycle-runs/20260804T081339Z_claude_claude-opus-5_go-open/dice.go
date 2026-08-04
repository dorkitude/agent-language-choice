package main

import (
	"errors"
	"net/http"
	"regexp"
	"strconv"
	"strings"
)

// ---------- POST /v1/dice/stats ----------

type diceRequest struct {
	Expression *string `json:"expression"`
}

type diceResponse struct {
	DiceCount int     `json:"dice_count"`
	Sides     int     `json:"sides"`
	Modifier  int     `json:"modifier"`
	Min       int     `json:"min"`
	Max       int     `json:"max"`
	Average   float64 `json:"average"`
}

// diceRe matches NdM with an optional signed flat modifier, e.g. "2d6+3". The
// anchors are deliberate: trailing junk must be rejected, not ignored.
var diceRe = regexp.MustCompile(`^([0-9]+)[dD]([0-9]+)([+-][0-9]+)?$`)

// parseDice splits a dice expression into its three components. The returned
// error text is surfaced verbatim to the client as a 400 message.
func parseDice(expr string) (count, sides, modifier int, err error) {
	m := diceRe.FindStringSubmatch(strings.TrimSpace(expr))
	if m == nil {
		return 0, 0, 0, errors.New("invalid expression")
	}
	count, err = strconv.Atoi(m[1])
	if err != nil {
		return 0, 0, 0, errors.New("invalid count")
	}
	sides, err = strconv.Atoi(m[2])
	if err != nil {
		return 0, 0, 0, errors.New("invalid sides")
	}
	if m[3] != "" {
		modifier, err = strconv.Atoi(m[3])
		if err != nil {
			return 0, 0, 0, errors.New("invalid modifier")
		}
	}
	// The regexp already excludes signs, so only a literal zero can land here.
	if count <= 0 || sides <= 0 {
		return 0, 0, 0, errors.New("count and sides must be positive")
	}
	return count, sides, modifier, nil
}

func handleDiceStats(w http.ResponseWriter, r *http.Request) {
	var req diceRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Expression == nil {
		writeError(w, http.StatusBadRequest, "expression is required")
		return
	}
	count, sides, modifier, err := parseDice(*req.Expression)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, diceResponse{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       count + modifier,
		Max:       count*sides + modifier,
		// Each die averages (sides+1)/2; the modifier is flat.
		Average: float64(count)*(float64(sides)+1)/2 + float64(modifier),
	})
}
