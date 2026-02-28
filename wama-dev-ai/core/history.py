"""
WAMA Dev AI - Persistent Conversation History

Saves conversation sessions to ~/.wama-dev-ai/history/<session_id>.json
so that context is retained across CLI restarts.

Each session file contains:
  - session_id   : timestamp-based unique ID (YYYYMMDD_HHMMSS)
  - timestamp    : ISO datetime of last save
  - last_request : last natural-language request string
  - messages     : full message list (role/content dicts, Ollama format)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

HISTORY_DIR = Path.home() / '.wama-dev-ai' / 'history'


class ConversationHistory:
    """
    Manages persistent conversation history across CLI sessions.

    Usage:
        history = ConversationHistory()

        # Save after each agentic loop
        history.save(request, messages)

        # Load previous session
        data = history.load_last()
        if data:
            messages = data['messages']

        # List available sessions
        for s in history.list_sessions():
            print(s['session_id'], s['summary'])
    """

    def __init__(self):
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        # Each CLI run has its own session file
        self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._session_file = HISTORY_DIR / f"{self.session_id}.json"
        self._last_request: Optional[str] = None
        self._messages: List[Dict] = []

    # -------------------------------------------------------------------------
    # Save / load
    # -------------------------------------------------------------------------

    def save(self, request: str, messages: List[Dict]) -> None:
        """Persist the current conversation to disk (overwrites same session)."""
        self._last_request = request
        self._messages = list(messages)

        data = {
            'session_id': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'last_request': request,
            'messages': messages,
        }
        try:
            self._session_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding='utf-8',
            )
        except OSError as e:
            logger.warning(f"[history] Could not save session: {e}")

    def load_last(self) -> Optional[Dict]:
        """
        Load the most recent previous session (not the current one).

        Returns the raw session dict, or None if no history exists.
        """
        files = self._sorted_files()
        # Skip the current session file if it already exists
        for f in files:
            if f.stem != self.session_id:
                return self._read_file(f)
        return None

    def load_session(self, session_id: str) -> Optional[Dict]:
        """Load a specific session by its ID string."""
        f = HISTORY_DIR / f"{session_id}.json"
        if f.exists():
            return self._read_file(f)
        return None

    # -------------------------------------------------------------------------
    # Listing
    # -------------------------------------------------------------------------

    def list_sessions(self, limit: int = 10) -> List[Dict]:
        """
        Return metadata for the N most recent sessions.

        Each entry has:
          session_id, timestamp, last_request (truncated), message_count
        """
        result = []
        for f in self._sorted_files()[:limit]:
            data = self._read_file(f)
            if data is None:
                continue
            msgs = data.get('messages', [])
            # Build a short summary from assistant turns
            assistant_msgs = [m['content'] for m in msgs if m.get('role') == 'assistant']
            snippet = assistant_msgs[-1][:120].replace('\n', ' ') if assistant_msgs else ''
            result.append({
                'session_id': data.get('session_id', f.stem),
                'timestamp': data.get('timestamp', ''),
                'last_request': (data.get('last_request') or '')[:80],
                'message_count': len(msgs),
                'last_reply_snippet': snippet,
                '_file': f,
            })
        return result

    # -------------------------------------------------------------------------
    # In-memory accessors
    # -------------------------------------------------------------------------

    @property
    def messages(self) -> List[Dict]:
        return self._messages

    @property
    def last_request(self) -> Optional[str]:
        return self._last_request

    def tail(self, n: int = 6) -> List[Dict]:
        """Return the last N messages from the current session (for context injection)."""
        return self._messages[-n:] if self._messages else []

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def _sorted_files(self) -> List[Path]:
        return sorted(HISTORY_DIR.glob('*.json'), reverse=True)

    def _read_file(self, f: Path) -> Optional[Dict]:
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"[history] Cannot read {f}: {e}")
            return None
