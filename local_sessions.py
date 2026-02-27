"""
local_sessions.py — Fetch and read local Copilot CLI sessions.

Adapted from copilot_session_fetch.py.
Provides functions to:
  1. Trigger a fetch of sessions from the Copilot CLI into data/
  2. List already-fetched sessions with summaries
  3. Read a full session and parse it into chat messages
"""

import asyncio
import json
import os
import threading
from datetime import datetime
from copilot import CopilotClient

# Output directory (relative to this module)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")

_fetch_lock = threading.Lock()


def ensure_dirs():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def parse_time(iso_str: str) -> str:
    """Convert ISO timestamp to a human-readable local time string."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_str


def dump_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)


# ── Async fetch logic ────────────────────────────────────────────────────────

async def _fetch_sessions_from_cli(limit: int = 50) -> dict:
    """Fetch sessions from the Copilot CLI and save to data/."""
    ensure_dirs()

    github_token = (
        os.environ.get("COPILOT_GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )

    if github_token:
        client = CopilotClient({
            "github_token": github_token,
            "use_logged_in_user": False,
        })
    else:
        client = CopilotClient()

    await client.start()

    try:
        response = await client._client.request("session.list", {})
        sessions = response if isinstance(response, list) else response.get("sessions", [])
        sessions.sort(key=lambda s: s.get("startTime", ""), reverse=True)

        total = len(sessions)
        display = sessions[:limit]

        # Write sessions.json
        sessions_path = os.path.join(DATA_DIR, "sessions.json")
        dump_json(sessions_path, display)

        # Fetch individual session events
        fetched = 0
        for s in display:
            sid = s.get("sessionId", "unknown")
            try:
                await client.resume_session(sid)
                result = await client._client.request(
                    "session.getMessages", {"sessionId": sid}
                )
                events = result.get("events", [])
            except Exception:
                events = []

            session_data = {**s, "events": events}
            out_path = os.path.join(SESSIONS_DIR, f"{sid}.json")
            dump_json(out_path, session_data)
            fetched += 1

        return {
            "total_found": total,
            "fetched": fetched,
            "status": "ok",
        }
    finally:
        await client.stop()


def fetch_sessions_sync(limit: int = 50) -> dict:
    """Synchronous wrapper to fetch sessions from CLI."""
    with _fetch_lock:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_fetch_sessions_from_cli(limit))
        finally:
            loop.close()


# ── Read already-fetched sessions ─────────────────────────────────────────────

def list_local_sessions() -> list:
    """
    Read data/sessions.json and return session metadata list.
    Each item has: sessionId, summary, startTime, modifiedTime, context.
    """
    sessions_path = os.path.join(DATA_DIR, "sessions.json")
    if not os.path.exists(sessions_path):
        return []

    with open(sessions_path, "r", encoding="utf-8") as f:
        sessions = json.load(f)

    result = []
    for s in sessions:
        summary = s.get("summary", "")
        # Truncate very long summaries (some are full system prompts)
        if len(summary) > 120:
            summary = summary[:117] + "..."

        result.append({
            "sessionId": s.get("sessionId"),
            "summary": summary,
            "startTime": s.get("startTime", ""),
            "startTimeLocal": parse_time(s.get("startTime", "")),
            "modifiedTime": s.get("modifiedTime", ""),
            "modifiedTimeLocal": parse_time(s.get("modifiedTime", "")),
            "cwd": s.get("context", {}).get("cwd", ""),
            "repository": s.get("context", {}).get("repository", ""),
            "branch": s.get("context", {}).get("branch", ""),
        })

    return result


def get_session_messages(session_id: str) -> dict:
    """
    Read a full session file and parse events into a chat message list.

    Returns:
        {
            "sessionId": ...,
            "summary": ...,
            "messages": [{"role": "user"|"agent", "text": "..."}],
            "metadata": {...}
        }
    """
    session_path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(session_path):
        return None

    with open(session_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = []
    current_assistant_parts = []

    for event in data.get("events", []):
        etype = event.get("type", "")
        edata = event.get("data", {})

        if etype == "user.message":
            # Flush any pending assistant message
            if current_assistant_parts:
                text = "".join(current_assistant_parts).strip()
                if text:
                    messages.append({"role": "agent", "text": text})
                current_assistant_parts = []

            content = edata.get("content", "")
            if content.strip():
                messages.append({"role": "user", "text": content.strip()})

        elif etype == "assistant.message":
            content = edata.get("content", "")
            if content:
                current_assistant_parts.append(content)

        elif etype == "assistant.turn_end":
            if current_assistant_parts:
                text = "".join(current_assistant_parts).strip()
                if text:
                    messages.append({"role": "agent", "text": text})
                current_assistant_parts = []

    # Flush any remaining assistant content
    if current_assistant_parts:
        text = "".join(current_assistant_parts).strip()
        if text:
            messages.append({"role": "agent", "text": text})

    summary = data.get("summary", "")
    if len(summary) > 120:
        summary = summary[:117] + "..."

    return {
        "sessionId": session_id,
        "summary": summary,
        "startTime": data.get("startTime", ""),
        "modifiedTime": data.get("modifiedTime", ""),
        "messages": messages,
        "metadata": {
            "cwd": data.get("context", {}).get("cwd", ""),
            "repository": data.get("context", {}).get("repository", ""),
            "branch": data.get("context", {}).get("branch", ""),
            "totalEvents": len(data.get("events", [])),
        }
    }
