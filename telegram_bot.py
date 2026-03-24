"""
telegram_bot.py — Telegram integration via python-telegram-bot (long-polling).

Runs a Telegram bot in a background thread alongside the Flask server.
Uses the same agent pipeline as the web UI and WhatsApp.

Commands:
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

import asyncio
import threading
import uuid
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from agent import (
    ask_agent,
    list_skill_directories,
    list_mcp_servers,
    list_custom_agents,
    list_available_models,
    get_default_model,
)
from local_sessions import list_local_sessions, get_session_messages, fetch_sessions_sync

# ── Per-user session state ─────────────────────────────────────────────────────
_tg_sessions: dict[int, dict] = {}

TELEGRAM_MSG_LIMIT = 4096


def _get_tg_session(user_id: int) -> dict:
    """Get or create a Telegram session state for a user."""
    if user_id not in _tg_sessions:
        _tg_sessions[user_id] = {
            "history": [],
            "skills": [],
            "mcps": [],
            "agents": [],
            "model": None,
            "resumed_session_id": None,
            "ui_session_id": f"telegram-{user_id}",
        }
    return _tg_sessions[user_id]


def _chunk_message(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> list[str]:
    """Split long text into Telegram-safe chunks."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at < limit * 0.3:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text.strip():
        chunks.append(text)
    return chunks


# ── Auth decorator ─────────────────────────────────────────────────────────────

def _auth_check(allowed_user_id: int):
    """Decorator to restrict bot access to a single user."""
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_user.id != allowed_user_id:
                await update.message.reply_text("🚫 Unauthorized.")
                return
            return await func(update, context)
        return wrapper
    return decorator


# ── Command handlers ───────────────────────────────────────────────────────────

async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = _get_tg_session(update.effective_user.id)
    await update.message.reply_text(
        "👋 *Local Pilot — Telegram*\n\n"
        "Chat with your GitHub Copilot agent from anywhere\\.\n\n"
        "Just type a message to start, or use /help for commands\\.",
        parse_mode="MarkdownV2",
    )


async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Agent Chat — Commands*\n\n"
        "💬 Just type naturally to chat with the agent.\n\n"
        "/skills — list available skills\n"
        "/mcps — list available MCP servers\n"
        "/agents — list available custom agents\n"
        "/models — list available models\n"
        "/model <id> — switch model\n"
        "/use #skill %mcp @agent — select tools\n"
        "/config — show current session config\n"
        "/sessions — list local Copilot sessions\n"
        "/resume <id> — resume a session\n"
        "/new — start a fresh session\n"
        "/help — show this message",
    )


async def _cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    skills = list_skill_directories()
    if not skills:
        await update.message.reply_text("No skills available.")
        return
    lines = ["*Available Skills:*\n"]
    for s in skills:
        lines.append(f"  #{s['slug']} — {s.get('description', s.get('name', ''))}")
    lines.append("\nUse /use #slug to activate.")
    await update.message.reply_text("\n".join(lines))


async def _cmd_mcps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mcps = list_mcp_servers()
    if not mcps:
        await update.message.reply_text("No MCP servers available.")
        return
    lines = ["*Available MCP Servers:*\n"]
    for m in mcps:
        lines.append(f"  %{m['slug']} — {m.get('description', m.get('name', ''))}")
    lines.append("\nUse /use %slug to activate.")
    await update.message.reply_text("\n".join(lines))


async def _cmd_agents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agents = list_custom_agents()
    if not agents:
        await update.message.reply_text("No custom agents available.")
        return
    lines = ["*Available Custom Agents:*\n"]
    for a in agents:
        lines.append(f"  @{a['slug']} — {a.get('description', a.get('name', ''))}")
    lines.append("\nUse /use @slug to activate.")
    await update.message.reply_text("\n".join(lines))


async def _cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    models = list_available_models()
    default = get_default_model()
    if not models:
        await update.message.reply_text("No models available.")
        return
    lines = ["Available Models:\n"]
    for m in models:
        marker = " ← current default" if m["id"] == default else ""
        lines.append(f"  🧠 {m['id']} — {m.get('description', m.get('name', ''))}{marker}")
    lines.append("\nUse /model <id> to switch. Example: /model claude-sonnet-4")
    await update.message.reply_text("\n".join(lines))


async def _cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = _get_tg_session(update.effective_user.id)
    args = " ".join(context.args).strip() if context.args else ""
    if not args:
        current = session.get("model") or get_default_model()
        await update.message.reply_text(
            f"Current model: 🧠 {current}\nUse /model <id> to switch.\nUse /models to see available models."
        )
        return
    valid_models = {m["id"] for m in list_available_models()}
    if args not in valid_models:
        await update.message.reply_text(f"❌ Unknown model: {args}\nUse /models to see available options.")
        return
    session["model"] = args
    await update.message.reply_text(f"✅ Model switched to 🧠 {args}")


async def _cmd_use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = _get_tg_session(update.effective_user.id)
    args = " ".join(context.args).strip() if context.args else ""
    if not args:
        await update.message.reply_text(
            "Usage: /use #skill-slug %mcp-slug @agent-slug\n"
            "Example: /use #code-review %workiq @web-search"
        )
        return

    tokens = args.split()
    new_skills = [t[1:] for t in tokens if t.startswith("#")]
    new_mcps = [t[1:] for t in tokens if t.startswith("%")]
    new_agents = [t[1:] for t in tokens if t.startswith("@")]

    valid_skills = {s["slug"] for s in list_skill_directories()}
    valid_mcps = {m["slug"] for m in list_mcp_servers()}
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
        await update.message.reply_text(
            f"❌ Unknown: {', '.join(bad)}\nUse /skills, /mcps, or /agents to see what's available."
        )
        return

    if new_skills:
        session["skills"] = new_skills
    if new_mcps:
        session["mcps"] = new_mcps
    if new_agents:
        session["agents"] = new_agents

    parts = []
    if new_skills:
        parts.append("Skills → " + ", ".join(f"#{s}" for s in new_skills))
    if new_mcps:
        parts.append("MCPs → " + ", ".join(f"%{s}" for s in new_mcps))
    if new_agents:
        parts.append("Agents → " + ", ".join(f"@{a}" for a in new_agents))
    await update.message.reply_text("✅ Updated.\n" + "\n".join(parts))


async def _cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = _get_tg_session(update.effective_user.id)
    skills_str = ", ".join(f"#{s}" for s in session["skills"]) if session["skills"] else "none"
    mcps_str = ", ".join(f"%{s}" for s in session.get("mcps", [])) if session.get("mcps") else "none"
    agents_str = ", ".join(f"@{a}" for a in session.get("agents", [])) if session.get("agents") else "none"
    model_str = session.get("model") or get_default_model()
    resumed = session["resumed_session_id"] or "none"
    msg_count = len(session["history"])
    await update.message.reply_text(
        f"Current Session Config:\n\n"
        f"Model: 🧠 {model_str}\n"
        f"Skills: {skills_str}\n"
        f"MCPs: {mcps_str}\n"
        f"Agents: {agents_str}\n"
        f"Resumed from: {resumed}\n"
        f"Messages in history: {msg_count}"
    )


async def _cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = _get_tg_session(update.effective_user.id)
    session["history"] = []
    session["skills"] = []
    session["mcps"] = []
    session["agents"] = []
    session["model"] = None
    session["resumed_session_id"] = None
    session["ui_session_id"] = f"telegram-{update.effective_user.id}-{uuid.uuid4().hex[:8]}"
    await update.message.reply_text(
        "🆕 Session reset. You're starting fresh.\n"
        "Use /use to set skills/MCPs/agents, /model to change model, or just start chatting."
    )


async def _cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Fetching sessions...")
    try:
        fetch_sessions_sync(20)
    except Exception:
        pass
    sessions = list_local_sessions()
    if not sessions:
        await update.message.reply_text("No local sessions found.")
        return
    lines = ["Recent Copilot Sessions:\n"]
    for s in sessions[:10]:
        sid = s.get("sessionId", "?")
        summary = s.get("summary", "Untitled")
        time_str = s.get("startTimeLocal", "")
        short_id = sid[:12]
        line = f"  {short_id} — {summary}"
        if time_str:
            line += f" ({time_str})"
        lines.append(line)
    lines.append(f"\nUse /resume <id> to continue a session.")
    await update.message.reply_text("\n".join(lines))


async def _cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = _get_tg_session(update.effective_user.id)
    session_id = " ".join(context.args).strip() if context.args else ""
    if not session_id:
        await update.message.reply_text("Usage: /resume <session-id>\nUse /sessions to find IDs.")
        return

    all_sessions = list_local_sessions()
    match = None
    for s in all_sessions:
        sid = s.get("sessionId", "")
        if sid == session_id or sid.startswith(session_id):
            match = sid
            break

    if not match:
        await update.message.reply_text(f"❌ No session found matching {session_id}\nUse /sessions to see available sessions.")
        return

    detail = get_session_messages(match)
    if detail and detail.get("messages"):
        session["history"] = [
            {"role": m["role"], "text": m["text"]}
            for m in detail["messages"]
        ]
    session["resumed_session_id"] = match
    summary = detail.get("summary", "session") if detail else "session"
    await update.message.reply_text(
        f"📂 Resumed: {summary}\n"
        f"History loaded ({len(session['history'])} messages). Send a message to continue."
    )


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages — send to the agent."""
    user_id = update.effective_user.id
    session = _get_tg_session(user_id)
    message = update.message.text.strip()

    if not message:
        return

    # Show "typing" indicator
    await update.message.chat.send_action("typing")

    history = list(session["history"])
    session["history"].append({"role": "user", "text": message})

    # Run agent in a thread to not block the event loop
    loop = asyncio.get_event_loop()
    try:
        reply = await loop.run_in_executor(
            None,
            lambda: ask_agent(
                message,
                history,
                resumed_session_id=session.get("resumed_session_id"),
                skill_slugs=session.get("skills", []),
                ui_session_id=session.get("ui_session_id"),
                mcp_slugs=session.get("mcps", []),
                agent_slugs=session.get("agents", []),
                model=session.get("model"),
            ),
        )
        session["history"].append({"role": "agent", "text": reply})

        # Send in chunks if too long
        for chunk in _chunk_message(reply):
            await update.message.reply_text(chunk)

    except Exception as e:
        await update.message.reply_text(f"❌ Agent error: {e}")


# ── Bot startup ────────────────────────────────────────────────────────────────

def start_telegram_bot():
    """Start the Telegram bot in a background thread (long-polling)."""
    try:
        from telegram_config import TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_ID
    except ImportError:
        print("[Telegram] ⚠ telegram_config.py not found — Telegram bot disabled.")
        print("[Telegram]   Create telegram_config.py with TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_ID")
        return

    if not TELEGRAM_BOT_TOKEN or "YOUR" in TELEGRAM_BOT_TOKEN:
        print("[Telegram] ⚠ telegram_config.py has placeholder values — Telegram bot disabled.")
        return

    auth = _auth_check(TELEGRAM_ALLOWED_USER_ID)

    def _run_bot():
        """Run the bot in its own event loop (runs in a background thread)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Register command handlers (all auth-wrapped)
        app.add_handler(CommandHandler("start", auth(_cmd_start)))
        app.add_handler(CommandHandler("help", auth(_cmd_help)))
        app.add_handler(CommandHandler("skills", auth(_cmd_skills)))
        app.add_handler(CommandHandler("mcps", auth(_cmd_mcps)))
        app.add_handler(CommandHandler("agents", auth(_cmd_agents)))
        app.add_handler(CommandHandler("models", auth(_cmd_models)))
        app.add_handler(CommandHandler("model", auth(_cmd_model)))
        app.add_handler(CommandHandler("use", auth(_cmd_use)))
        app.add_handler(CommandHandler("config", auth(_cmd_config)))
        app.add_handler(CommandHandler("new", auth(_cmd_new)))
        app.add_handler(CommandHandler("sessions", auth(_cmd_sessions)))
        app.add_handler(CommandHandler("resume", auth(_cmd_resume)))

        # Regular messages
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auth(_handle_message)))

        print(f"[Telegram] ✓ Bot started (polling) — allowed user: {TELEGRAM_ALLOWED_USER_ID}")
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
        )

    thread = threading.Thread(target=_run_bot, daemon=True)
    thread.start()
    print("[Telegram] ✓ Bot thread launched")
