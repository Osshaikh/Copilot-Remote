# Copilot Remote — Access GitHub Copilot from Your Phone via Telegram

A self-hosted agent that wraps the **GitHub Copilot SDK** behind a Flask server with a **Telegram bot** for remote access — chat with Copilot from your phone, no browser or ngrok needed.

```
┌──────────────┐    Telegram API     ┌────────────────┐     Copilot SDK      ┌───────────┐
│  Your Phone  │ ◄─────────────────► │  Flask server  │ ◄──────────────────► │  GitHub   │
│  (Telegram)  │  (long-polling,     │  + Telegram    │   sessions & tools   │  Copilot  │
└──────────────┘   no ports needed)  │  bot thread    │                      └───────────┘
                                     └────────────────┘
                                           │
                                     ┌─────┴──────┐
                                     │  Optional  │
                                     │  Browser   │
                                     │  Chat UI   │
                                     │ (localhost) │
                                     └────────────┘
```

## Why Telegram?

| | Telegram Bot | WhatsApp (Twilio) | ngrok + Browser |
|---|---|---|---|
| **Setup** | 1 step (BotFather token) | 4+ steps (Twilio account, ngrok, webhook, phone number) |  2 steps (ngrok account + tunnel) |
| **Cost** | Free | ~$0.005/message + phone number fee | Free (limited) or paid |
| **Inbound ports** | None (outbound polling) | Yes (webhook needs public URL) | Yes (tunnel) |
| **Moving parts** | Flask + bot thread | Flask + ngrok + Twilio + webhook | Flask + ngrok |
| **Works offline?** | Bot queues messages | Breaks if ngrok is down | Breaks if ngrok is down |

## Features

- **Telegram bot** — chat with Copilot from your phone using simple commands, no browser needed
- **Browser UI** — optional dark-themed, mobile-responsive chat interface (`index.html`) on localhost
- **Streaming responses** — real-time SSE streaming in the browser UI with tool-call visibility
- **Skills** — add skill directories under `skills/` with a `SKILL.md` for domain-specific knowledge
- **MCP Servers** — connect external tool servers via `mcp.json` — the agent can invoke their tools
- **Custom Agents** — define specialised agent personas in `agents.json` with custom prompts and tools
- **18 models** — switch between Claude, GPT, and Gemini models via `/model` command or UI dropdown
- **Reasoning display** — models with thinking tokens show chain-of-thought in the browser UI
- **Local session browser** — fetch, view, and resume past Copilot CLI sessions
- **Workspace sandbox** — file operations default to `pilot_folder/` for safety
- **Auto-start** — optional Windows Task Scheduler setup for always-on operation

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.11+** | For the Flask backend |
| **GitHub Copilot access** | A valid GitHub token with Copilot entitlements |
| **Telegram account** | And a bot created via [@BotFather](https://t.me/BotFather) |

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure GitHub authentication

The server picks up a GitHub token from environment variables (checked in order):

```bash
# Option A: Copilot-specific token
export COPILOT_GITHUB_TOKEN="ghp_..."

# Option B: Standard GitHub CLI token
export GH_TOKEN="ghp_..."

# Option C: Generic
export GITHUB_TOKEN="ghp_..."
```

If none are set, the SDK falls back to the logged-in GitHub CLI user (`gh auth status`).

### 3. Set up Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, follow the prompts, and copy the **bot token**
3. Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot)
4. Create `telegram_config.py` in the project root:

```python
TELEGRAM_BOT_TOKEN = "123456789:ABCdef..."
TELEGRAM_ALLOWED_USER_ID = 123456789
```

### 4. Start the server

```bash
python app.py
```

You'll see:
```
[Telegram] ✓ Bot thread launched
[Telegram] ✓ Bot started (polling) — allowed user: 123456789

  Agent chat server running → http://localhost:5000
```

### 5. Chat on Telegram

Open your bot on Telegram and send `/start` — you're ready to chat with Copilot!

## Telegram Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Show all commands |
| `/models` | List available AI models |
| `/model <id>` | Switch model (e.g., `/model claude-sonnet-4.6`) |
| `/skills` | List available skills |
| `/mcps` | List available MCP servers |
| `/agents` | List available custom agents |
| `/use #skill %mcp @agent` | Activate skills, MCPs, or agents |
| `/config` | Show current session config |
| `/sessions` | List recent local Copilot CLI sessions |
| `/resume <id>` | Resume a past session |
| `/new` | Start a fresh session |
| Any text | Sent directly to the Copilot agent |

## Project Structure

```
copilot-remote/
├── app.py                 # Flask server — REST + SSE endpoints + Telegram bot startup
├── agent.py               # Copilot SDK wrapper — session management, streaming
├── telegram_bot.py        # Telegram bot — long-polling, commands, chat forwarding
├── telegram_config.py     # Telegram credentials (⚠ do not commit)
├── local_sessions.py      # Fetch & browse past Copilot CLI sessions
├── whatsapp.py            # WhatsApp integration via Twilio webhooks (optional)
├── teams.py               # Teams integration via Azure Bot Framework (optional)
├── index.html             # Self-contained browser chat UI (optional)
├── start.cmd              # Windows launcher script
├── requirements.txt       # Python dependencies
├── mcp.json               # MCP server configurations
├── agents.json            # Custom agent definitions (prompts, tools, MCPs)
├── models_config.json     # Available models and default model selection
├── skills/                # Skill directories (each has a SKILL.md)
│   ├── code-review/
│   ├── docs-writer/
│   ├── security-audit/
│   └── testing/
└── pilot_folder/          # Default workspace for file operations
    └── src/
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check — returns `{"status": "ok"}` |
| `POST` | `/chat` | Send a message, get a full reply (non-streaming) |
| `POST` | `/chat/stream` | Send a message, receive SSE stream with deltas + tool events |
| `GET` | `/skills` | List available skills |
| `GET` | `/mcps` | List available MCP servers |
| `GET` | `/agents` | List available custom agents |
| `GET` | `/models` | List available models and the default model |
| `GET` | `/local-sessions` | List previously fetched Copilot CLI sessions |
| `POST` | `/local-sessions/fetch` | Trigger a fresh fetch of sessions from Copilot CLI |
| `GET` | `/local-sessions/<id>` | Get full conversation for a local session |

## Skills

Add a directory under `skills/` with a `SKILL.md` file:

```markdown
---
name: Code Review
description: Provides structured code review with quality scoring
---

# Code Review Skill

When performing code reviews, follow this structured approach...
```

Skills appear in the **# Skills** dropdown and inject domain-specific instructions into the agent.

## MCP Servers

Configure external tool servers in `mcp.json`:

```json
{
  "workiq": {
    "command": "npx",
    "args": ["-y", "@microsoft/workiq", "mcp"]
  }
}
```

Each key becomes a selectable MCP server in the **⚡ MCPs** dropdown. The agent can invoke tools provided by these servers during conversations.

## Custom Agents

Define specialised agent personas in `agents.json`:

```json
{
  "web-search": {
    "name": "Web Search",
    "description": "Agent with web browsing capabilities",
    "prompt": "You are a research assistant with web access...",
    "tools": ["web_fetch"]
  },
  "work-iq": {
    "name": "Work IQ",
    "description": "Agent powered by Microsoft Work IQ",
    "prompt": "You are an intelligent work assistant...",
    "mcp_servers": {
      "workiq": {
        "command": "npx",
        "args": ["-y", "@microsoft/workiq", "mcp"]
      }
    }
  }
}
```

Each key becomes a selectable agent in the **🤖 Agents** dropdown. Agents can have:

| Field | Description |
|---|---|
| `name` | Display name in the UI |
| `description` | Short description shown in the dropdown |
| `prompt` | System prompt that defines the agent's persona and behaviour |
| `tools` | List of built-in tool names the agent should use (e.g., `web_fetch`) |
| `mcp_servers` | Embedded MCP server configs that are activated when this agent is selected |

## Models

Configure available models in `models_config.json`. 18 models are included by default:

- **Claude:** Sonnet 4.6, Sonnet 4.5, Haiku 4.5, Opus 4.6, Opus 4.6 (1M), Opus 4.5, Sonnet 4
- **GPT:** 5.4, 5.3-Codex, 5.2-Codex, 5.2, 5.1-Codex-Max, 5.1-Codex, 5.1, 5.1-Codex-Mini, 5-Mini, 4.1
- **Gemini:** 3 Pro (Preview)

Switch models via `/model <id>` on Telegram or the 🧠 dropdown in the browser UI.

Models that emit reasoning / thinking tokens (e.g., Claude Sonnet 4) will have their chain-of-thought rendered in a collapsible "Thinking…" block in the chat UI.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `PORT` | `5000` | Flask server port |
| `COPILOT_WORKSPACE` | `./pilot_folder` | Working directory for file operations |
| `COPILOT_GITHUB_TOKEN` | — | GitHub token for Copilot SDK |
| `GH_TOKEN` | — | Fallback GitHub token |
| `GITHUB_TOKEN` | — | Second fallback GitHub token |

| Config File | Description |
|---|---|
| `telegram_config.py` | Telegram bot token + allowed user ID (⚠ do not commit) |
| `models_config.json` | Available models and default model |
| `agents.json` | Custom agent personas with prompts and tools |
| `mcp.json` | MCP server configurations |

## Other Integrations (Optional)

The Telegram bot is the primary interface, but the following are also supported:

- **Browser UI** — open `index.html` locally (or via ngrok for remote access)
- **WhatsApp** — via Twilio webhooks (requires Twilio account + ngrok)
- **Microsoft Teams** — via Azure Bot Framework

For setup instructions, see **[docs/integration_setup_guide.md](docs/integration_setup_guide.md)** and **[docs/technical_design.md](docs/technical_design.md)**.

## Auto-Start on Boot (Windows)

To keep the bot running permanently, set up a Windows Task Scheduler task:

```powershell
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument '/c "path\to\start.cmd"' `
    -WorkingDirectory "path\to\copilot-remote"

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Seconds 60) `
    -ExecutionTimeLimit (New-TimeSpan -Days 9999)

Register-ScheduledTask -TaskName "CopilotRemote" `
    -Action $action -Trigger $trigger -Settings $settings `
    -User $env:USERNAME -RunLevel Highest -Force
```

Or simply double-click `start.cmd` to run manually.

## License

Private / Internal use.
