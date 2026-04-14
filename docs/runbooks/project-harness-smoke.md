# Project Harness Smoke Test

## Goal

Validate that the project harness shell works end to end on current stores.

## Steps

1. Start the server locally.
2. Open the dashboard.
3. Confirm `Projects` route loads.
4. Confirm project list renders from `/api/projects`.
5. Open one project cockpit.
6. Confirm active cycle, next action, and evidence render.
7. Launch or inspect an existing mission from the cockpit.
8. Confirm drill-down to mission and task details still works.

## Expected Result

The operator can navigate planning and execution continuity from one project surface without losing access to existing detail pages.
