package main

import (
	"encoding/json"
	"strings"
)

// Request-field readers shared by every endpoint.
//
// Optional-vs-missing is distinguished by decoding into pointer fields
// (*string, *bool) or *json.RawMessage. RawMessage is used wherever a numeric
// field must reject wrong-typed input — plain `int` would silently accept
// `null` and `1.5` would be truncated by some decoders — so numbers always go
// through asInt.

// asInt strictly interprets a raw JSON value as an integer. It rejects a
// missing field, null, strings, booleans, and non-integral numbers.
func asInt(raw *json.RawMessage) (int, bool) {
	if raw == nil {
		return 0, false
	}
	var n json.Number
	if err := json.Unmarshal(*raw, &n); err != nil {
		return 0, false
	}
	v, err := n.Int64()
	if err != nil {
		return 0, false
	}
	return int(v), true
}

// crKey normalizes a challenge rating that may arrive as a JSON string
// ("1/4", "5") or as a number (5). Fractional ratings are only expressible as
// strings, so both spellings must be accepted for the same monster.
func crKey(raw *json.RawMessage) (string, bool) {
	if raw == nil {
		return "", false
	}
	var s string
	if err := json.Unmarshal(*raw, &s); err == nil {
		return strings.TrimSpace(s), true
	}
	var n json.Number
	if err := json.Unmarshal(*raw, &n); err == nil {
		return n.String(), true
	}
	return "", false
}

// requiredString reads a present, non-blank string field and returns it
// trimmed. Stored identifiers (slugs, campaign ids, names) all go through here
// so persisted keys never carry surrounding whitespace.
func requiredString(v *string) (string, bool) {
	if v == nil {
		return "", false
	}
	s := strings.TrimSpace(*v)
	if s == "" {
		return "", false
	}
	return s, true
}
