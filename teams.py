"""
teams.py — Microsoft Teams integration via Azure Bot Framework webhooks.

Registers a /teams endpoint on the Flask app that receives incoming
Teams messages, routes them through the existing agent pipeline,
and replies back.

Setup:
  1. Create teams_config.py with:
       TEAMS_APP_ID     = "your-microsoft-app-id"
       TEAMS_APP_PASSWORD = "your-client-secret"
  2. In Azure Bot → Configuration, set Messaging Endpoint to:
       https://YOUR-NGROK-URL/teams
  3. In Azure Bot → Channels, enable Microsoft Teams

Commands (identical to WhatsApp integration):
  /skills              — list available skills
  /mcps                — list available MCP servers
  /agents              — list available custom agents
  /models              — list available models
  /model <id>          — switch model for your session
  /use #slug #slug     — select skills for your session
  /use %slug %slug     — select MCP servers for your session
  /use @slug @slug     — select custom agents for your session
  /config              — show current session config
  /sessions            — list recent local Copilot sessions
  /resume <id>         — resume a local Copilot session
  /new                 — start a fresh session
  /help                — show this help
  (anything else)      — sent as a chat message to the agent
"""

import threading
import time
import requests
from flask import request, jsonify

from agent import ask_agent, list_skill_directories, list_mcp_servers, list_custom_agents, list_available_models, get_default_model
from local_sessions import list_local_sessions, get_session_messages, fetch_sessions_sync


# ── Per-user session state ─────────────────────────────────────────────────────
# Keyed by Teams user ID (from activity["from"]["id"])
_teams_sessions: dict[str, dict] = {}


def _get_teams_session(user_id: str) -> dict:
    """Get or create a Teams session state for a user."""
    if user_id not in _teams_sessions:
        _teams_sessions[user_id] = {
            "history": [],
            "skills": [],
            "mcps": [],
            "agents": [],
            "model": None,
            "resumed_session_id": None,
        }
    return _teams_sessions[user_id]


def _truncate(text: str, limit: int = 4000) -> str:
    """Teams supports up to ~28k chars but keep it reasonable."""
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


# ── Bot Framework Auth ─────────────────────────────────────────────────────────

_token_cache = {"token": None, "expires_at": 0}


def _get_bot_token(app_id: str, app_password: str, tenant_id: str = "botframework.com") -> str:
    """Get or refresh the Bot Framework access token."""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    resp = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": app_id,
            "client_secret": app_password,
            "scope": "https://api.botframework.com/.default",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _token_cache["token"]


def _send_teams_reply(activity: dict, text: str, app_id: str, app_password: str, tenant_id: str = "botframework.com"):
    """Send a reply back to Teams using the Bot Framework REST API."""
    service_url = activity.get("serviceUrl", "").rstrip("/")
    conversation_id = activity["conversation"]["id"]
    activity_id = activity.get("id", "")

    reply_url = f"{service_url}/v3/conversations/{conversation_id}/activities/{activity_id}"

    reply = {
        "type": "message",
        "from": {"id": app_id},
        "conversation": activity["conversation"],
        "recipient": activity["from"],
        "replyToId": activity_id,
        "text": text,
    }

    try:
        token = _get_bot_token(app_id, app_password, tenant_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(reply_url, json=reply, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[Teams] Failed to send reply: {e}")


# ── Command handlers (mirrors whatsapp.py) ────────────────────────────────────

def _handle_help() -> str:
    return (
        "🤖 **Agent Chat — Teams Commands**\n\n"
        "💬 Just type naturally to chat with the agent.\n\n"
        "• **/skills** — list available skills\n"
        "• **/mcps** — list available MCP servers\n"
        "• **/agents** — list available custom agents\n"
        "• **/models** — list available models\n"
        "• **/model <id>** — switch model (e.g. /model claude-sonnet-4)\n"
        "• **/use #code-review** — select skills\n"
        "• **/use %workiq** — select MCP servers\n"
        "• **/use @web-search** — select custom agents\n"
        "• **/config** — show current session config\n"
        "• **/sessions** — list local Copilot sessions\n"
        "• **/resume <id>** — resume a session\n"
        "• **/new** — start a fresh session\n"
        "• **/help** — show this message"
    )


def _handle_skills() -> str:
    skills = list_skill_directories()
    if not skills:
        return "No skills available."
    lines = ["**Available Skills:**\n"]
    for s in skills:
        lines.append(f"  #{s['slug']} — {s.get('description', s.get('name', ''))}")
    lines.append("\nUse **/use #slug** to activate one or more.")
    return "\n".join(lines)


def _handle_mcps() -> str:
    mcps = list_mcp_servers()
    if not mcps:
        return "No MCP servers available."
    lines = ["**Available MCP Servers:**\n"]
    for m in mcps:
        lines.append(f"  %{m['slug']} — {m.get('description', m.get('name', ''))}")
    lines.append("\nUse **/use %slug** to activate one or more.")
    return "\n".join(lines)


def _handle_agents() -> str:
    agents = list_custom_agents()
    if not agents:
        return "No custom agents available."
    lines = ["**Available Custom Agents:**\n"]
    for a in agents:
        lines.append(f"  @{a['slug']} — {a.get('description', a.get('name', ''))}")
    lines.append("\nUse **/use @slug** to activate one or more.")
    return "\n".join(lines)


def _handle_models() -> str:
    models = list_available_models()
    default = get_default_model()
    if not models:
        return "No models available."
    lines = ["**Available Models:**\n"]
    for m in models:
        marker = " ← current default" if m['id'] == default else ""
        lines.append(f"  🧠 {m['id']} — {m.get('description', m.get('name', ''))}{marker}")
    lines.append("\nUse /model id to switch. Example: */model claude-sonnet-4*")
    return "\n".join(lines)


def _handle_model(args: str, session: dict) -> str:
    model_id = args.strip()
    if not model_id:
        current = session.get("model") or get_default_model()
        return f"Current model: 🧠 **{current}**\nUse **/model id** to switch.\nUse **/models** to see available models."

    valid_models = {m["id"] for m in list_available_models()}
    if model_id not in valid_models:
        return f"❌ Unknown model: `{model_id}`\nUse **/models** to see available options."

    session["model"] = model_id
    return f"✅ Model switched to 🧠 **{model_id}**"


def _handle_use(args: str, session: dict) -> str:
    tokens = args.split()
    new_skills = [t[1:] for t in tokens if t.startswith("#")]
    new_mcps   = [t[1:] for t in tokens if t.startswith("%")]
    new_agents = [t[1:] for t in tokens if t.startswith("@")]

    valid_skills = {s["slug"] for s in list_skill_directories()}
    valid_mcps   = {m["slug"] for m in list_mcp_servers()}
    valid_agents = {a["slug"] for a in list_custom_agents()}

    bad = []
    for slug in new_skills:
        if slug not in valid_skills:
            bad.append(f"#{slug}")
    for slug in new_mcps:
        if slug not in valid_mcps:
            bad.append(f"%{slug}")
    for slug in new_agents:
        if slug not in valid_agents:
            bad.append(f"@{slug}")

    if bad:
        return f"❌ Unknown: {', '.join(bad)}\nUse **/skills**, **/mcps**, or **/agents** to see what's available."

    if new_skills:
        session["skills"] = new_skills
    if new_mcps:
        session["mcps"] = new_mcps
    if new_agents:
        session["agents"] = new_agents

    if not new_skills and not new_mcps and not new_agents:
        return "Usage: **/use #skill-slug %mcp-slug @agent-slug**"

    parts = []
    if new_skills:
        parts.append("Skills → " + ", ".join(f"#{s}" for s in new_skills))
    if new_mcps:
        parts.append("MCPs → " + ", ".join(f"%{s}" for s in new_mcps))
    if new_agents:
        parts.append("Agents → " + ", ".join(f"@{a}" for a in new_agents))
    return "✅ Updated.\n" + "\n".join(parts)


def _handle_config(session: dict) -> str:
    skills_str = ", ".join(f"#{s}" for s in session["skills"]) if session["skills"] else "none"
    mcps_str   = ", ".join(f"%{s}" for s in session.get("mcps", [])) if session.get("mcps") else "none"
    agents_str = ", ".join(f"@{a}" for a in session.get("agents", [])) if session.get("agents") else "none"
    model_str  = session.get("model") or get_default_model()
    resumed    = session["resumed_session_id"] or "none"
    msg_count  = len(session["history"])
    return (
        f"**Current Session Config:**\n\n"
        f"Model: 🧠 {model_str}\n"
        f"Skills: {skills_str}\n"
        f"MCPs: {mcps_str}\n"
        f"Agents: {agents_str}\n"
        f"Resumed from: {resumed}\n"
        f"Messages in history: {msg_count}"
    )


def _handle_new(session: dict) -> str:
    session["history"] = []
    session["skills"] = []
    session["mcps"] = []
    session["agents"] = []
    session["model"] = None
    session["resumed_session_id"] = None
    return "🆕 Session reset. You're starting fresh.\nUse **/use** to set skills/MCPs/agents, **/model** to change model, or just start chatting."


def _handle_sessions() -> str:
    try:
        fetch_sessions_sync(20)
    except Exception:
        pass

    sessions = list_local_sessions()
    if not sessions:
        return "No local sessions found."

    lines = ["**Recent Copilot Sessions:**\n"]
    for s in sessions[:10]:
        sid = s.get("sessionId", "?")
        summary = s.get("summary", "Untitled")
        time_str = s.get("startTimeLocal", "")
        short_id = sid[:12]
        line = f"  `{short_id}` — {summary}"
        if time_str:
            line += f" ({time_str})"
        lines.append(line)
    lines.append("\nUse **/resume <id>** to continue a session.")
    return "\n".join(lines)


def _handle_resume(args: str, session: dict) -> str:
    session_id = args.strip()
    if not session_id:
        return "Usage: **/resume <session-id>**\nUse **/sessions** to find IDs."

    all_sessions = list_local_sessions()
    match = None
    for s in all_sessions:
        sid = s.get("sessionId", "")
        if sid == session_id or sid.startswith(session_id):
            match = sid
            break

    if not match:
        return f"❌ No session found matching `{session_id}`.\nUse **/sessions** to see available sessions."

    detail = get_session_messages(match)
    if detail and detail.get("messages"):
        session["history"] = [
            {"role": m["role"], "text": m["text"]}
            for m in detail["messages"]
        ]
    session["resumed_session_id"] = match
    summary = detail.get("summary", "session") if detail else "session"
    return (
        f"📂 Resumed: **{summary}**\n"
        f"History loaded ({len(session['history'])} messages). Send a message to continue."
    )


def _handle_chat(message: str, session: dict, activity: dict, app_id: str, app_password: str, tenant_id: str = "botframework.com") -> str:
    """
    Send message to agent. If fast enough, return inline reply.
    Otherwise send 'thinking...' immediately and deliver real reply async.
    Teams requires a response within 5 seconds — async handles longer calls.
    """
    history = list(session["history"])
    session["history"].append({"role": "user", "text": message})

    result_holder = {"reply": None, "error": None}

    def _call_agent():
        try:
            reply = ask_agent(
                message, history,
                resumed_session_id=session.get("resumed_session_id"),
                skill_slugs=session.get("skills", []),
                mcp_slugs=session.get("mcps", []),
                agent_slugs=session.get("agents", []),
                model=session.get("model"),
            )
            result_holder["reply"] = reply
        except Exception as e:
            result_holder["error"] = str(e)

    t = threading.Thread(target=_call_agent)
    t.start()
    t.join(timeout=4)  # Teams needs response in ~5s; leave 1s buffer

    if result_holder["reply"] is not None:
        reply = result_holder["reply"]
        session["history"].append({"role": "agent", "text": reply})
        return _truncate(reply)

    if result_holder["error"] is not None:
        return f"❌ Agent error: {result_holder['error']}"

    # Still running — send placeholder, deliver real reply async
    def _send_async():
        t.join()
        if result_holder["reply"]:
            reply = result_holder["reply"]
            session["history"].append({"role": "agent", "text": reply})
        elif result_holder["error"]:
            reply = f"❌ Agent error: {result_holder['error']}"
        else:
            reply = "❌ Agent timed out. Try a simpler question."

        _send_teams_reply(activity, _truncate(reply), app_id, app_password, tenant_id)

    threading.Thread(target=_send_async, daemon=True).start()
    return "⏳ Thinking... I'll send the full reply in a moment."


# ── Flask registration ─────────────────────────────────────────────────────────

def register_teams_routes(app):
    """Register the /teams webhook route on the given Flask app."""

    try:
        from teams_config import TEAMS_APP_ID, TEAMS_APP_PASSWORD, TEAMS_TENANT_ID
    except ImportError:
        print("[Teams] ⚠ teams_config.py not found — Teams endpoint disabled.")
        print("[Teams]   Create teams_config.py with TEAMS_APP_ID, TEAMS_APP_PASSWORD, and TEAMS_TENANT_ID")
        return

    if "PASTE_YOUR" in TEAMS_APP_ID or "PASTE_YOUR" in TEAMS_APP_PASSWORD:
        print("[Teams] ⚠ teams_config.py has placeholder values — Teams endpoint disabled.")
        return

    print(f"[Teams] ✓ Azure Bot configured — App ID: {TEAMS_APP_ID[:8]}... Tenant: {TEAMS_TENANT_ID[:8]}...")

    @app.route("/teams", methods=["POST"])
    def teams_webhook():
        """Azure Bot Framework sends incoming Teams messages here."""
        activity = request.get_json(force=True, silent=True)
        if not activity:
            return jsonify({"error": "Invalid payload"}), 400

        # Only handle actual messages (ignore typing indicators, etc.)
        if activity.get("type") != "message":
            return jsonify({}), 200

        user_id = activity.get("from", {}).get("id", "unknown")
        body = (activity.get("text") or "").strip()

        if not body:
            _send_teams_reply(activity, "Send a message or type **/help** for commands.", TEAMS_APP_ID, TEAMS_APP_PASSWORD, TEAMS_TENANT_ID)
            return jsonify({}), 200

        session = _get_teams_session(user_id)
        text = body.strip()

        # Route commands — mirrors whatsapp.py exactly
        if text.lower() == "/help":
            reply = _handle_help()
        elif text.lower() == "/skills":
            reply = _handle_skills()
        elif text.lower() == "/mcps":
            reply = _handle_mcps()
        elif text.lower() == "/agents":
            reply = _handle_agents()
        elif text.lower() == "/models":
            reply = _handle_models()
        elif text.lower().startswith("/model "):
            reply = _handle_model(text[7:], session)
        elif text.lower() == "/model":
            reply = _handle_model("", session)
        elif text.lower().startswith("/use "):
            reply = _handle_use(text[5:], session)
        elif text.lower() == "/use":
            reply = _handle_use("", session)
        elif text.lower() == "/config":
            reply = _handle_config(session)
        elif text.lower() == "/new":
            reply = _handle_new(session)
        elif text.lower() == "/sessions":
            reply = _handle_sessions()
        elif text.lower().startswith("/resume "):
            reply = _handle_resume(text[8:], session)
        elif text.lower() == "/resume":
            reply = _handle_resume("", session)
        else:
            reply = _handle_chat(text, session, activity, TEAMS_APP_ID, TEAMS_APP_PASSWORD, TEAMS_TENANT_ID)

        # For non-async replies, send directly
        if reply:
            _send_teams_reply(activity, reply, TEAMS_APP_ID, TEAMS_APP_PASSWORD, TEAMS_TENANT_ID)

        return jsonify({}), 200

    print("[Teams] ✓ /teams endpoint registered")