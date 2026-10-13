# Reddit publishing bridge

MYCELIX can publish its public manifesto through a manually triggered GitHub Actions workflow.

## Current Reddit access requirement

As of Reddit's 2026 Responsible Builder Policy, explicit approval is required before using Reddit's API. This repository therefore blocks publication until Reddit approval is recorded.

Official access request form:
https://support.reddithelp.com/hc/en-us/requests/new?ticket_form_id=14868593862164

Official policy:
https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy

For this project the requested scope should stay narrow:

- manual self-post publishing only;
- no voting;
- no direct messages;
- no automated commenting;
- no scraping or bulk export;
- no use of Reddit user content for AI/model training;
- no commercial outreach.

## Safety model

- The workflow is manual only (`workflow_dispatch`).
- The default action is `validate`, which performs no publication.
- Publication requires Reddit approval recorded as repository variable `REDDIT_API_APPROVED=true`.
- Publication also requires both `action = publish` and `confirm = PUBLISH`.
- Reddit OAuth credentials are read only from GitHub Actions Secrets.
- The publisher never prints the client secret or refresh token.
- This workflow is separate from the Render deployment workflow.

## Required repository variable

After Reddit has approved the API use case, create this Actions repository variable:

- `REDDIT_API_APPROVED` = `true`

Do not set it to true before approval.

## Required GitHub Secrets

After approval and OAuth credentials are available, create these repository Actions secrets:

- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_REFRESH_TOKEN`

The refresh token must belong to the Reddit user authorized to submit the post.

## OAuth flow

Use the OAuth method and credentials Reddit provides or approves for the external integration.

The publisher expects:

1. Reddit-issued/approved client ID and client secret.
2. A user authorization with a refresh token that can submit posts.
3. The refresh token stored as `REDDIT_REFRESH_TOKEN`.

Never commit credentials or tokens.

## Validate now

Open:

**Actions → Publish MYCELIX Reddit manifesto → Run workflow**

Use:

- action: `validate`
- subreddit: `AI_Agents`
- confirm: leave empty

This requires no Reddit credentials and does not publish.

## Publish after approval

After the repository variable and three secrets are configured:

- action: `publish`
- subreddit: `AI_Agents`
- confirm: `PUBLISH`

The workflow obtains a short-lived OAuth access token, submits a self-post to Reddit, and writes the resulting post URL into the GitHub Actions job summary.
