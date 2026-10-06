# W30 review repair: only the current trip request may render or land

the operator approved current error-card landing on 2026-10-06. This supersedes the original brief's exclusion of failure landing. Build lane: headless CodeBuddy, deepseek-v4.1-flash, max effort. Parent owns all execution, tests, hashes and browser verification. You have Read/Edit/Glob/Grep only.

## Scope

Edit **only `ui/party/party.js`**. No CSS, HTML, tests, docs, other files, settings, commands, commits or pushes. Preserve the existing W30 viewport-fit layout and all unrelated logic. Read `party.js` and the new `tests/test_w30_trip_requests.py` before editing.

## Reproduced failures

- After choosing A, Continue, Back, choosing B, Continue, the held response for A overwrites B's pending or completed list and scrolls the page again. An old failure clears the new list, retaining a enabled Continue when a new trip was already selected. Reopening A itself is also vulnerable, so checking category equality is insufficient.
- Back must invalidate an outstanding request even if no new request starts. Category reset must also invalidate it immediately. Every new `loadTrips` invocation gets a unique epoch.
- A current request failure renders the error but doesn't land its card. On 800×320 the heading ends up above the viewport. the operator approved bringing the current error card into view too. Superseded failures do nothing.

## Required implementation

**Parent follow-up:** a current failure followed by Back and Continue without reselecting the category leaves the previous error visible during Loading and after successful trips render. Add `clearError("trip-error")` at the start of each new `loadTrips`, before the loading placeholder. Keep the epoch guards unchanged. The eleventh lifecycle test is RED until this reset exists. This is the same request-lifecycle repair, not a new UI scope.

Use a monotonically increasing request epoch. Increment on new load, category reset and trip Back. Capture the epoch in `loadTrips`. Check ownership at the START of both successful and failed callbacks, before changing state, children, errors, disabled controls or scroll position. A superseded result must not render or land. Both rider and driver share this code.

Call the existing `landTripCard()` after the current error is displayed, just as it is called after a current populated/empty list is rendered. Keep the helper's hidden-step guard. Keep the existing style: var, function, double quotes, two-space indent, a short comment explaining request ownership. Avoid AbortController and broad refactors.

## Verification owned by parent

`tests/test_w30_trip_requests.py` has ten deterministic driven tests covering stale success/failure, same/different categories, immediately after Back, category reset, a pending or already selected new list, empty stale response, current failure landing, successive Continue activations, and details→Back successful re-entry. These go RED before your edit. `tests/browser/w30_trip_requests.cjs` covers actual gated requests and error-card geometry on both pages. The original viewport/fade/hover/keyboard contract stays unchanged apart from the disclosed mouse-parking correction.

Four party.js SHA freezes will fail after your edit. Parent re-baselines them only after inspecting your exact diff. Do not edit tests yourself. Report exact functions/handlers touched and files edited, then stop.
