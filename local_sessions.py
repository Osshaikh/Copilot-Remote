"""
local_sessions.py — Fetch and browse Copilot CLI sessions (fully in-memory).

Uses the same Copilot SDK RPCs as copilot_session_fetch.py but keeps
everything in memory — no data/ folder required.

Flow:
  1. User clicks "Fetch Local Sessions"  →  fetch_sessions_sync()
     - Talks to the Copilot CLI via session.list + session.getMessages RPCs
     - Stores session metadata + events in _session_store
  2. list_local_sessions()  →  returns summaries from _session_store
  3. get_session_messages(id) → parses events from _session_store into chat msgs
"""

import asyncio
import os
import threading
from datetime import datetime
from copilot import CopilotClient

_fetch_lock = threading.Lock()

# ── In-memory store ───────────────────────────────────────────────────────────
# _session_index: list of session metadata dicts (from session.list)
# _session_events: dict mapping sessionId → full session dict (metadata + events)
_session_index: list = []
_session_events: dict[str, dict] = {}


def parse_time(iso_str: str) -> str:
    """Convert ISO timestamp to a human-readable local time string."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_str


# ── Async fetch logic (talks to Copilot CLI) ─────────────────────────────────

async def _fetch_sessions_from_cli(limit: int = 50) -> dict:
    """
    Fetch sessions from the Copilot CLI and store in memory.
    Same RPCs as copilot_session_fetch.py: session.list + session.getMessages.
    """
    global _session_index, _session_events

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
        # ── session.list RPC ──────────────────────────────────
        response = await client._client.request("session.list", {})
        sessions = response if isinstance(response, list) else response.get("sessions", [])
        sessions.sort(key=lambda s: s.get("startTime", ""), reverse=True)

        total = len(sessions)
        display = sessions[:limit]

        # Store index in memory
        _session_index = display

        # ── Fetch events for each session ─────────────────────
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

            _session_events[sid] = {**s, "events": events}
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


# ── Read from in-memory store ─────────────────────────────────────────────────

def list_local_sessions() -> list:
    """
    Return session metadata from the in-memory store.
    Returns an empty list if fetch hasn't been called yet.
    """
    result = []
    for s in _session_index:
        summary = s.get("summary", "")
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


def get_session_messages(session_id: str) -> dict | None:
    """
    Parse events from the in-memory store into a chat message list.

    Returns:
        {
            "sessionId": ...,
            "summary": ...,
            "messages": [{"role": "user"|"agent", "text": "..."}],
            "metadata": {...}
        }
        or None if session_id hasn't been fetched.
    """
    data = _session_events.get(session_id)
    if data is None:
        return None

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
