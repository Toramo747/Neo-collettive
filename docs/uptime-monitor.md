# External uptime monitor for MYCELIX

This procedure keeps Neo-collettive responsive during the approved operating window without changing the Render plan.

Target:
- URL: https://neo-collettive.onrender.com/health
- Method: GET
- Interval while active: every 5 minutes
- Operating window: **07:00-23:00 Europe/Rome**
- Cost target: zero
- Accounts are created and owned manually by Andrea. No automated sign-up is authorized.

## Preferred: cron-job.org

cron-job.org supports explicit schedule hours, minutes and time zone, so it can enforce the daily operating window without a paid service.

1. Andrea creates or signs in to the cron-job.org account manually.
2. Create a new cron job.
3. Set the URL to `https://neo-collettive.onrender.com/health`.
4. Use HTTP method `GET`.
5. Enable the job.
6. Set the schedule time zone to `Europe/Rome`.
7. Configure the minutes as:
   `00,05,10,15,20,25,30,35,40,45,50,55`.
8. Configure the hours as:
   `07,08,09,10,11,12,13,14,15,16,17,18,19,20,21,22`.
   This produces 5-minute checks from 07:00 through 22:55 and no scheduled checks outside the approved 07:00-23:00 window.
9. Configure all days of week, all days of month and all months.
10. Save the job and confirm from its execution history that HTTP 200 responses are being returned.
11. Do not add authentication headers, credentials, POST bodies or any state-changing request.

cron-job.org's documented schedule model supports a time zone plus explicit hour and minute arrays:
https://docs.cron-job.org/rest-api.html

## Alternative: UptimeRobot

The UptimeRobot Free plan supports HTTP monitoring every 5 minutes.

1. Andrea creates or signs in to the UptimeRobot account manually.
2. Select **Add New Monitor**.
3. Choose **HTTP(s)**.
4. Enter `https://neo-collettive.onrender.com/health`.
5. Set the monitoring interval to 5 minutes.
6. Add Andrea's preferred email alert contact.
7. Save and verify that the monitor reports HTTP success.

Important zero-cost limitation: recurring Maintenance Windows are a paid UptimeRobot feature. Therefore the Free plan cannot automatically enforce the required 07:00-23:00 daily monitoring window. Under the zero-cost constraint, UptimeRobot should be used only if Andrea is willing to pause/resume it manually each day. For automatic daily time-window scheduling, use cron-job.org.

References:
- https://help.uptimerobot.com/en/articles/11360876-what-is-a-monitoring-interval-in-uptimerobot
- https://help.uptimerobot.com/en/articles/11360884-what-is-a-maintenance-window-and-how-to-use-it-in-uptimerobot

## 70% Free-instance-hour warning

The workspace limit is 750 Free instance hours per calendar month.
70% of the limit is **525 hours**.

Render's documented Billing page exposes the workspace's Monthly Included Usage and Render sends email notifications when usage is approaching a limit, but the public documentation does not provide a configurable custom 70% Free-instance-hour alert.

Zero-cost operating procedure:
1. Keep Render's account email notifications enabled.
2. Check **Billing -> Monthly Included Usage -> Free Instance Hours** at least weekly and additionally near month end.
3. Treat **525 hours** as the internal warning threshold.
4. At or above 525 hours, review the remaining-month budget before extending monitoring hours. Do not change a Render plan or delete/suspend a service automatically.
5. If an exact automatic 70% threshold becomes available in Render's supported UI/API in the future, it may be enabled only as a read-only notification; no automatic billing or plan changes.

Render reference:
https://render.com/docs/free

## Expected budget

The 07:00-23:00 window is 16 hours/day:
- 30-day month: 480 hours for Neo-collettive if continuously kept awake during the window.
- 31-day month: 496 hours.

The workspace safety ceiling used by this project is 637.5 hours (85% of 750), preserving a 15% reserve for other Free web services.
