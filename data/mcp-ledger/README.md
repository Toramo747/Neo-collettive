# mcp-ledger — a dated ledger of MCP tool contracts

**What this is.** Once a day, neo reads the public handshake of the remote servers listed in the official MCP
registry — `initialize` and `tools/list` only, cursors followed, never a tool call, no credentials, one read per
server per day — and records a digest of each server's tool contract (tool names, descriptions, input schemas,
annotations). The rows of a day are summarised in a Merkle root; the root is named in the day's receipt-log anchor,
which is timestamped on Bitcoin (OpenTimestamps) and archived by Software Heritage. Later, "server S exposed the
contract with digest D on day T" can be proved from the row, its inclusion path and the anchor — by anyone, without
trusting neo.

**What is public here.**
- `days/<date>.json.gz` — rows `[server_key, contract_digest or "", outcome, tool_count]`, sorted by `server_key`, plus the day's root.
- `days/<date>.root.json` — the root, counts by outcome, latency percentiles, duration. Aggregates only.
- `state.json.gz` — per server key: last digest, first seen, change dates (last 30), gaps, recent digests.

`server_key = sha256("neo-mcp-ledger-v1" || 0x00 || canonical_url)[:32]`. Whoever knows a server's URL can recompute
its key and check its rows; nobody can learn a URL from this directory. **No server name or URL is published here.**
`contract_digest = sha256("neo-mcp-ledger-v1" || 0x01 || canonical_json(contract))`, where the contract is the tool
list sorted by name with the fields `name`, `description`, `inputSchema`, `annotations`.

Merkle leaves are `sha256(0x00 || canonical_json(row))`, nodes `sha256(0x01 || left || right)`, an odd last node is
duplicated. `python tools/mcp_ledger.py prove <date> <server_key>` prints a row's inclusion path and checks it.

**What is not here.** The contract texts themselves are kept in a private archive, content-addressed by digest, and
are only ever returned to a caller who asks about a specific URL (phase 2, paid, with a signed receipt). A gap
(unreachable, refused, timeout, a skipped run) is recorded as a gap, never as a change. Granularity is one read per
UTC day: the ledger proves what a server answered at that read, not what it served between two reads. Tools behind
authentication, per-client responses and the behaviour of the tools are outside its scope.

**Opting out.** This is the same public handshake any MCP client performs, with a declared User-Agent
(`neo-mcp-ledger/…`), at most one read per server per day and at most two concurrent requests per host. If you run a
server and do not want it read:
- serve a `2xx` at `https://<your host>/.well-known/mcp-ledger-opt-out` whose body contains the line `mcp-ledger-opt-out: yes` (checked once per host per week; a bare 200 on every path, or a page that echoes the path, does not count), or
- add your registry name or URL to `data/registry-health/opt-out.txt` in this repository (pull request or issue), or
- write to the suggestion box `POST https://neo-collettive.onrender.com/x402/suggest` with `{"want": "mcp-ledger opt-out <url>"}`.

No reason is required. From the next read your server is skipped; its archived contract texts are deleted and only
the digests already anchored remain (they cannot be removed from past anchors, and they name nothing).

**Status.** Measurement phase from 29/10/2026: a fixed subset of the registry is read until a week of real numbers
(duration, refusals, gaps) justifies the full read. Until then any public statement says "N servers read per day".
