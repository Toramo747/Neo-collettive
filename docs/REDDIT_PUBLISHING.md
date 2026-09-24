# Reddit publishing bridge

MYCELIX can publish its public manifesto through a manually triggered GitHub Actions workflow.

## Safety model

- The workflow is manual only (`workflow_dispatch`).
- The default action is `validate`, which performs no publication.
- Publication requires both `action = publish` and `confirm = PUBLISH`.
- Reddit OAuth credentials are read only from GitHub Actions Secrets.
- The publisher never prints the client secret or refresh token.
- This workflow is separate from the Render deployment workflow.

## Required GitHub Secrets

Create these repository Actions secrets:

- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_REFRESH_TOKEN`

The refresh token must belong to a Reddit user that authorized the application with permission to submit posts.

## OAuth flow

1. Create or configure a Reddit OAuth application.
2. Authorize the Reddit user with permanent duration and the `submit` scope.
3. Exchange the authorization code at `https://www.reddit.com/api/v1/access_token`.
4. Store the returned refresh token in `REDDIT_REFRESH_TOKEN`.
5. Store the application client ID and secret in the matching GitHub Secrets.

Never commit credentials or tokens.

## Validate

Open:

**Actions → Publish MYCELIX Reddit manifesto → Run workflow**

Use:

- action: `validate`
- subreddit: `AI_Agents`
- confirm: leave empty

## Publish

After the secrets are configured:

- action: `publish`
- subreddit: `AI_Agents`
- confirm: `PUBLISH`

The workflow obtains a short-lived OAuth access token, submits a self-post to Reddit, and writes the resulting post URL into the GitHub Actions job summary.
