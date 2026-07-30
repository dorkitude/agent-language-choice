package eval

func calendarAndWeatherSuite() Suite {
	base := worldEventsSuite()
	return Suite{ID: "068-calendar-and-weather", Name: "Campaign Play 068: Calendar and Weather", Tests: append(base.Tests,
		playTest("play-calendar-get-uninitialized", "Uninitialized calendar returns 404", "GET", "/v1/play/campaigns/play-1/calendar", nil, map[string]string{"Authorization": playerAAuth}, 404, nil),
		playTest("play-calendar-advance-uninitialized", "Uninitialized calendar cannot advance", "POST", "/v1/play/campaigns/play-1/calendar/advance", map[string]any{"days": 1}, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTest("play-calendar-player-init-forbidden", "Players cannot initialize the calendar", "POST", "/v1/play/campaigns/play-1/calendar", map[string]any{"day": 1, "season": "spring"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-calendar-invalid-day", "Calendar day must be at least one", "POST", "/v1/play/campaigns/play-1/calendar", map[string]any{"day": 0, "season": "spring"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-calendar-invalid-season", "Calendar season must be known", "POST", "/v1/play/campaigns/play-1/calendar", map[string]any{"day": 1, "season": "monsoon"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-calendar-init", "DM initializes calendar with deterministic weather", "POST", "/v1/play/campaigns/play-1/calendar", map[string]any{"day": 1, "season": "spring"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"day": 1, "season": "spring", "weather": "rain"}),
		playTest("play-calendar-duplicate-init", "Calendar initializes only once", "POST", "/v1/play/campaigns/play-1/calendar", map[string]any{"day": 2, "season": "summer"}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTestExactJSON("play-calendar-read-player", "Campaign player reads exact calendar", "GET", "/v1/play/campaigns/play-1/calendar", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"day": 1, "season": "spring", "weather": "rain"}),
		playTest("play-calendar-player-advance-forbidden", "Players cannot advance the calendar", "POST", "/v1/play/campaigns/play-1/calendar/advance", map[string]any{"days": 5}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-calendar-invalid-advance-zero", "Calendar advance requires at least one day", "POST", "/v1/play/campaigns/play-1/calendar/advance", map[string]any{"days": 0}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-calendar-invalid-advance-large", "Calendar advance is capped at thirty days", "POST", "/v1/play/campaigns/play-1/calendar/advance", map[string]any{"days": 31}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-calendar-advance", "DM advances calendar and receives deterministic weather", "POST", "/v1/play/campaigns/play-1/calendar/advance", map[string]any{"days": 5}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"day": 6, "season": "spring", "weather": "wind"}),
		playTestExactJSON("play-calendar-read-dm-after-advance", "DM reads advanced exact calendar", "GET", "/v1/play/campaigns/play-1/calendar", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"day": 6, "season": "spring", "weather": "wind"}),
	)}
}
