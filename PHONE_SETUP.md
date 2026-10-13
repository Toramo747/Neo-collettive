# NEO from a phone

The repository is ready for Docker deployment.

## Render

1. Sign in to Render and choose **New -> Blueprint**.
2. Connect GitHub and select `Toramo747/Neo-collettive`.
3. Render reads `render.yaml`. Create the service.
4. When deployment finishes, open `https://YOUR-RENDER-HOST/health`.
5. The MCP endpoint is `https://YOUR-RENDER-HOST/mcp`.

## ChatGPT

Create a custom MCP app in Developer Mode using the HTTPS `/mcp` URL, scan tools, and enable the app in a chat.

Expected tools:

- `neo_preflight`
- `neo_discover`
- `neo_ask_agents`
- `neo_collective`

v0.5 has no LAN access, shell, filesystem, credentials, or write actions.
