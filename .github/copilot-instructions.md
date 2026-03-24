# Copilot Instructions — Copilot Remote (Local Pilot)

## Architecture

This is a self-hosted agent that wraps the **GitHub Copilot SDK** (`github-copilot-sdk` Python package) behind a Flask server, with multiple messaging channels (Telegram, WhatsApp, Teams, browser UI) for remote access.

```
Channels (Telegram/WhatsApp/Teams/Browser)
    │
    ▼
app.py (Flask server — routes + channel startup)
    │
    ▼
ask_agent() / ask_agent_streaming()  ← agent.py
    │
    ├── _get_or_create_session()  — new conversations (keyed by ui_session_id or history hash)
    │   └── tries resume from .session_map.json first, then creates fresh
    │
    └── _get_or_resume_session()  — resume Copilot CLI sessions by ID
        │
        ▼
    CopilotClient (singleton) → Copilot SDK → GitHub Copilot API
```

**Key architectural decisions:**
- A single `CopilotClient` instance is shared across all channels (initialized in `_ensure_client()`)
- A single background asyncio event loop (`_ensure_loop()`) runs all SDK calls; channels use `asyncio.run_coroutine_threadsafe()` to bridge sync→async
- SDK sessions are cached in-memory (`_sessions` dict) and persisted to `.session_map.json` for restart recovery
- Config changes (model/skills/MCPs) are detected via fingerprinting (`_config_fingerprint()`); when config changes, the old session observer is soft-destroyed and re-resumed with new config — history is preserved server-side
- All tool permissions are auto-approved via `_approve_all_permissions()` — this is a single-user local setup

## Commands

```bash
# Install
pip install -r requirements.txt

# Run (starts Flask + Telegram bot)
python app.py

# Or via launcher (sets COPILOT_WORKSPACE)
start.cmd
```

No test suite, linter, or CI pipeline exists (aside from a GitHub Pages deploy workflow for `index.html`).

## Channel Pattern

All channels follow the same pattern. When adding a new channel:

1. Create `my_channel.py` with a per-user session state dict:
   ```python
   _sessions: dict[str, dict] = {}
   def _get_session(user_id):
       if user_id not in _sessions:
           _sessions[user_id] = {
               "history": [], "skills": [], "mcps": [], "agents": [],
               "model": None, "resumed_session_id": None,
               "ui_session_id": f"mychannel-{user_id}",
           }
       return _sessions[user_id]
   ```

2. Implement command handlers (`/help`, `/skills`, `/mcps`, `/agents`, `/models`, `/model`, `/use`, `/config`, `/sessions`, `/resume`, `/new`) — see `whatsapp.py` for the complete set.

3. Forward chat messages to the agent:
   ```python
   reply = ask_agent(message, history,
       skill_slugs=session["skills"],
       ui_session_id=session["ui_session_id"],
       mcp_slugs=session["mcps"],
       agent_slugs=session["agents"],
       model=session["model"],
   )
   ```

4. Register in `app.py` — webhook channels use `register_*_routes(app)`, polling channels use `start_*_bot()` in a daemon thread.

**Important:** `ui_session_id` must be a stable per-user identifier (e.g., `telegram-{user_id}`). Without it, the SDK creates a new server-side session for each message (context loss). The `/new` command should regenerate this with a UUID suffix.

## Session Management

- `_get_or_create_session(client, conversation_key, ...)` — the main session lookup. Checks in-memory cache → persisted `.session_map.json` → creates new.
- `_get_or_resume_session(client, session_id, ...)` — resumes a Copilot CLI session by its ID.
- Both detect config changes via `_session_config_cache` fingerprints and re-resume with new config while preserving server-side history.
- `_destroy_old_session()` cleans up observers to prevent duplicate streaming output.

## Config Files

| File | Schema | Purpose |
|------|--------|---------|
| `models_config.json` | `{ "default_model": "id", "models": [{"id", "name", "description"}] }` | Available models |
| `agents.json` | `{ "agents": { "slug": {"name", "display_name", "description", "prompt", "infer", "tools", "mcp_servers"} } }` | Custom agent personas |
| `mcp.json` | `{ "servers": { "slug": {"slug", "name", "description", "type", "command", "args", "tools"} } }` | MCP server definitions |
| `telegram_config.py` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID` | Telegram credentials (gitignored) |

## Conventions

- **Slugs** are lowercase-hyphenated (`code-review`, `web-search`, `workiq`). Users reference them with prefix markers: `#skill`, `%mcp`, `@agent`.
- **Skills** are directories under `skills/` with a `SKILL.md` containing YAML frontmatter (`name`, `description`). Use `.github/skills/make-skill-template/SKILL.md` as the reference for creating new ones.
- **Streaming vs sync:** The browser UI uses `ask_agent_streaming()` (SSE via `/chat/stream`). All messaging channels use `ask_agent()` (blocking). Both share the same session management.
- **Timeout handling:** WhatsApp has a 12s inline response window, Teams has 4s. Both fall back to async reply delivery if the agent is slow. Telegram has no timeout constraint (messages are sent when ready).
- **Flask debug mode must be off** (`debug=False` in `app.py`) — the watchdog reloader spawns duplicate processes that fight over the Telegram bot's polling connection.
- **`COPILOT_WORKSPACE` env var** controls the SDK's working directory and the system prompt's file access scope. Set in `start.cmd`.
