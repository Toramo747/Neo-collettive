# MYCELIX heartbeat operations

The canonical workflow is `.github/workflows/mycelix-heartbeat-v3.yml`.

## GitHub Actions cadence

The workflow requests a 30-minute cadence with the cron expression `17,47 * * * *`.
GitHub Actions does not guarantee that scheduled workflows start exactly on time; scheduled runs can be delayed or skipped during periods of load. The offsets are intentionally kept away from the top of the hour.

For this reason, GitHub Actions is not the mechanism that guarantees that the Render service remains awake.
The keep-awake role is assigned to an external uptime monitor that performs a lightweight HTTP GET against the production health endpoint during the configured operating window.

The external monitor must remain read-only and must target:

`https://neo-collettive.onrender.com/health`

Account creation and any external-service configuration requiring credentials are performed manually by Andrea.

## Scope

The heartbeat workflow remains responsible for:
- waking/checking the runtime when it runs;
- validating the production/runtime contract;
- recording endpoint latency observations;
- publishing the runtime snapshot.

It must not change Render plans, create paid resources, or perform external commercial actions.
