package eval

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"reflect"
	"strings"
	"time"
)

type RunConfig struct {
	BaseURL  string
	Suite    string
	Timeout  time.Duration
	FailFast bool
	Verbose  bool
}

type Report struct {
	Suite       string       `json:"suite"`
	BaseURL     string       `json:"base_url"`
	Passed      bool         `json:"passed"`
	PassedCount int          `json:"passed_count"`
	TotalCount  int          `json:"total_count"`
	Results     []TestResult `json:"results"`
}

type TestResult struct {
	ID           string `json:"id"`
	Name         string `json:"name"`
	Passed       bool   `json:"passed"`
	Status       int    `json:"status"`
	DurationMS   int64  `json:"duration_ms"`
	Error        string `json:"error,omitempty"`
	ResponseBody string `json:"response_body,omitempty"`
}

func Run(ctx context.Context, config RunConfig) (Report, error) {
	if config.BaseURL == "" {
		return Report{}, errors.New("base URL is required")
	}
	if config.Timeout <= 0 {
		return Report{}, errors.New("timeout must be positive")
	}
	if _, err := url.ParseRequestURI(config.BaseURL); err != nil {
		return Report{}, fmt.Errorf("invalid base URL: %w", err)
	}

	suite, ok := FindSuite(config.Suite)
	if !ok {
		return Report{}, fmt.Errorf("unknown suite %q", config.Suite)
	}

	client := &http.Client{Timeout: config.Timeout}
	report := Report{
		Suite:      suite.ID,
		BaseURL:    strings.TrimRight(config.BaseURL, "/"),
		TotalCount: len(suite.Tests),
	}

	for _, test := range suite.Tests {
		result := runTest(ctx, client, report.BaseURL, test, config.Verbose)
		report.Results = append(report.Results, result)
		if result.Passed {
			report.PassedCount++
		} else if config.FailFast {
			break
		}
	}
	report.Passed = report.PassedCount == report.TotalCount
	return report, nil
}

func runTest(ctx context.Context, client *http.Client, baseURL string, test Test, verbose bool) TestResult {
	started := time.Now()
	result := TestResult{ID: test.ID, Name: test.Name}

	body, err := encodeBody(test.Body)
	if err != nil {
		result.Error = err.Error()
		result.DurationMS = time.Since(started).Milliseconds()
		return result
	}

	req, err := http.NewRequestWithContext(ctx, test.Method, baseURL+test.Path, body)
	if err != nil {
		result.Error = err.Error()
		result.DurationMS = time.Since(started).Milliseconds()
		return result
	}
	if test.Body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		result.Error = err.Error()
		result.DurationMS = time.Since(started).Milliseconds()
		return result
	}
	defer resp.Body.Close()

	payload, readErr := io.ReadAll(resp.Body)
	result.Status = resp.StatusCode
	result.DurationMS = time.Since(started).Milliseconds()
	if readErr != nil {
		result.Error = readErr.Error()
		return result
	}
	if verbose || resp.StatusCode != test.WantStatus {
		result.ResponseBody = string(payload)
	}
	if resp.StatusCode != test.WantStatus {
		result.Error = fmt.Sprintf("status %d, want %d", resp.StatusCode, test.WantStatus)
		return result
	}
	if test.WantJSON == nil {
		result.Passed = true
		return result
	}

	var got any
	if err := json.Unmarshal(payload, &got); err != nil {
		result.ResponseBody = string(payload)
		result.Error = fmt.Sprintf("invalid JSON response: %v", err)
		return result
	}
	if err := jsonContains(got, normalizeJSONValue(test.WantJSON)); err != nil {
		result.ResponseBody = string(payload)
		result.Error = err.Error()
		return result
	}
	result.Passed = true
	return result
}

func encodeBody(body map[string]any) (io.Reader, error) {
	if body == nil {
		return nil, nil
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	return bytes.NewReader(payload), nil
}

func jsonContains(got any, want any) error {
	got = normalizeJSONValue(got)
	switch wantTyped := want.(type) {
	case map[string]any:
		gotMap, ok := got.(map[string]any)
		if !ok {
			return fmt.Errorf("JSON type mismatch: got %T, want object", got)
		}
		for key, wantValue := range wantTyped {
			gotValue, ok := gotMap[key]
			if !ok {
				return fmt.Errorf("missing JSON key %q", key)
			}
			if err := jsonContains(gotValue, wantValue); err != nil {
				return fmt.Errorf("%s: %w", key, err)
			}
		}
		return nil
	case []any:
		gotSlice, ok := got.([]any)
		if !ok {
			return fmt.Errorf("JSON type mismatch: got %T, want array", got)
		}
		if len(gotSlice) != len(wantTyped) {
			return fmt.Errorf("array length %d, want %d", len(gotSlice), len(wantTyped))
		}
		for i := range wantTyped {
			if err := jsonContains(gotSlice[i], wantTyped[i]); err != nil {
				return fmt.Errorf("[%d]: %w", i, err)
			}
		}
		return nil
	case float64:
		gotFloat, ok := got.(float64)
		if !ok {
			return fmt.Errorf("JSON type mismatch: got %T, want number", got)
		}
		if math.Abs(gotFloat-wantTyped) > 0.000001 {
			return fmt.Errorf("number %v, want %v", gotFloat, wantTyped)
		}
		return nil
	default:
		if !reflect.DeepEqual(got, want) {
			return fmt.Errorf("value %v, want %v", got, want)
		}
		return nil
	}
}

func normalizeJSONValue(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		out := make(map[string]any, len(typed))
		for key, value := range typed {
			out[key] = normalizeJSONValue(value)
		}
		return out
	case []map[string]any:
		out := make([]any, len(typed))
		for i, value := range typed {
			out[i] = normalizeJSONValue(value)
		}
		return out
	case []any:
		out := make([]any, len(typed))
		for i, value := range typed {
			out[i] = normalizeJSONValue(value)
		}
		return out
	case int:
		return float64(typed)
	case int64:
		return float64(typed)
	case float32:
		return float64(typed)
	default:
		return value
	}
}

func (report Report) Text() string {
	var builder strings.Builder
	fmt.Fprintf(&builder, "suite=%s base_url=%s passed=%v tests=%d/%d\n",
		report.Suite, report.BaseURL, report.Passed, report.PassedCount, report.TotalCount)
	for _, result := range report.Results {
		status := "PASS"
		if !result.Passed {
			status = "FAIL"
		}
		fmt.Fprintf(&builder, "%s\t%s\t%dms", status, result.ID, result.DurationMS)
		if result.Status != 0 {
			fmt.Fprintf(&builder, "\tHTTP %d", result.Status)
		}
		if result.Error != "" {
			fmt.Fprintf(&builder, "\t%s", result.Error)
		}
		builder.WriteString("\n")
		if result.ResponseBody != "" {
			fmt.Fprintf(&builder, "  response: %s\n", strings.TrimSpace(result.ResponseBody))
		}
	}
	return builder.String()
}
