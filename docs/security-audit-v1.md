# Security audit for version 1.0.0

Implemented security fixes; no commit or version change made. Restart the app and reload room tabs to activate them.

| Area | Finding and resulting behavior |
| --- | --- |
| Shared HTML/SVG credentials | Shared scripts could read the session token from their own URL. Shared content now receives an HMAC credential restricted to one file and room. Legacy session-token URLs redirect before serving content. Credentials are generated for current snapshots and folder children, not written into saved meetings. |
| Filesystem sharing | Native MCP sharing bypassed the existing out-of-folder approval gate. Single files and folders now resolve paths and symlinks before checking the agent workspace and configured `add_dirs`. Other paths require host approval unless that agent is explicitly in Auto mode. |
| Remote sharing | SSH rooms could request files from the local host through the sharing endpoint. They must now upload contents; local path reads are rejected even in Auto mode. |
| Active file formats | Unknown formats such as XHTML could execute on the hub origin when opened directly. They now download as binary attachments. HTML and SVG keep their CSP sandbox without `allow-same-origin`. Responses include `nosniff`. |
| SSH command injection | An SSH host beginning with an option could be interpreted as `ProxyCommand` or another SSH option. Host validation now runs before subprocess launch across probing, browsing, connection, shutdown and agent commands. Remote environment-variable names are also validated. Existing remote paths and argv remain shell quoted. |
| Browser rendering | Picker names, handles, providers and roles are HTML escaped. Hostile HTML, script tags, links, tables and code blocks were checked against the existing Markdown renderers. |
| Internal endpoints/uploads | Internal endpoints reject foreign and opaque browser origins while retaining header-authenticated native MCP access. Single-file uploads now enforce the same 50 MiB decoded limit and strict base64 validation as folders; empty uploads work. |

## Existing protections verified

The launcher binds Uvicorn to `127.0.0.1`, not all interfaces. HTTP Host checks reject DNS rebinding. Access tokens use constant-time comparison. Browser mutations and WebSocket connections require approved origins; WebSockets also require the session token. File lookup uses registered IDs rather than user-supplied URL paths. Saved-meeting session names reject traversal and out-of-root symlinks. Responses suppress referrers. Shell tools intentionally execute commands through the existing host approval mechanism; that is distinct from unintended injection into SSH setup.

## Validation

23 Python tests passed: 8 new security tests, 5 folder-sharing tests, 8 saved-meeting tests and 2 exit tests. The folder-sharing fixture explicitly grants its output folder via `add_dirs` to exercise the corrected permission boundary. New Node rendering checks and Python/JavaScript syntax checks also passed.

Checks cover denied and approved out-of-folder sharing, symlink escapes, normal workspace and extra-directory sharing, remote local-read rejection, empty and malformed uploads, restricted file credentials, legacy URL redirects, active-format downloads, host/token/origin/WebSocket guards, invalid SSH hosts, legitimate IPv6 destinations and shell-quoted remote paths. Full browser behavior was not manually verified; the separate release test task owns the full suite.

## Trust assumptions and limits

This remains a single-user local application. Native agents receive the session credential and are trusted participants, not mutually isolated tenants; this audit does not create a security boundary against a hostile agent or another process running as the same OS user. Explicit Auto approvals intentionally permit out-of-folder local shares. Shared HTML can run scripts and contact external sites within its existing sandbox, so keep outputs trusted before interacting with them. Body size checks run after receiving/decoding uploads and are not a streaming defense against memory exhaustion by an authenticated client.
