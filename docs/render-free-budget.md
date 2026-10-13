# Render Free instance budget

Checked 2026-09-27. This document is informational only and does not authorize plan or service changes.

## Verified workspace usage

The Render Billing screenshot supplied by Andrea shows:
- Free Instance Hours: 111.97 / 750 hours for the workspace.
- Included Services: 3 / 25.
- Included Bandwidth: 2.84 / 5 GB.

Render documents Free instance hours as a workspace-level monthly allowance. The documented service metrics include CPU, memory, requests, bandwidth and related telemetry, but do not expose a per-service Free-instance-hour counter. Therefore the 111.97 hours must not be allocated to individual services without a Render source that provides that breakdown.

Known service references in this repository:
- Neo-collettive production: https://neo-collettive.onrender.com
- Jarvis reference: https://jarvis-23lu.onrender.com
- A third workspace service is visible in the workspace service count, but it cannot be identified reliably from the repository data inspected here.

No service is classified as unused from this evidence alone.

Official references:
- https://render.com/docs/free
- https://render.com/docs/service-metrics
- https://render.com/docs/render-dashboard

## Limit behavior

Render grants 750 Free instance hours to each workspace per calendar month. A Free web service consumes hours while running and does not consume them while spun down. If the workspace consumes all 750 hours, Render suspends all Free web services until the start of the next month; the allowance then resets to 750.

A 15% safety reserve is 112.5 hours, so planned aggregate consumption should remain at or below 637.5 hours per month.

## Neo-collettive operating-window budget

If Neo-collettive remains awake 24/7:
- 30-day month: about 720 hours.
- 31-day month: about 744 hours.

This leaves effectively no safe shared budget for other Free web services.

Recommended conservative keep-awake window: **07:00-23:00 Europe/Rome** (16 hours/day).
- 30-day month: 480 hours.
- 31-day month: 496 hours.
- Remaining aggregate budget below the 637.5-hour safety ceiling in a 31-day month: 141.5 hours for all other Free web services.

A wider 07:00-24:00 window consumes 510 hours in a 30-day month and 527 hours in a 31-day month, leaving only 110.5 hours for other Free web services while preserving the 15% reserve. Use that wider window only after confirming the other services' monthly runtime consumption is low enough.

The external monitor should therefore use 07:00-23:00 Europe/Rome until a reliable per-service usage breakdown is available.
