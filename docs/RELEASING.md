# Releasing MYCELIX

GitHub releases are manual.

The automated MCP Registry publication workflow does not create Git tags or GitHub releases. In particular, no automation token is granted a GitHub App `workflows` permission in order to create or move tags that point at commits containing changes under `.github/workflows/`.

## Manual GitHub release

When a GitHub release is required:

1. Confirm the production version from `/health` and from `cloud_mcp.py`.
2. Confirm the intended commit has completed the required CI/deploy checks.
3. In the GitHub web interface, create the version tag manually on that exact commit.
4. Create the GitHub Release from that manually created tag.
5. Do not use an automation token with `workflows` permission to bypass GitHub's workflow-file protection.

The official MCP Registry publication is a separate process and uses GitHub OIDC through `.github/workflows/publish-mcp-registry.yml`.
