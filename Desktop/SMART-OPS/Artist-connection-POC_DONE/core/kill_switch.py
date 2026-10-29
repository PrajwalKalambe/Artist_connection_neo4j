"""
core/kill_switch.py

Enterprise-grade kill switch for all AI processing (intent, entity,
and explanation agents — i.e. every Ollama/LLM call).

Design goals:
  1. Controlled through .env (KILL_SWITCH_ENABLED=true/false).
  2. Immediate effect — no restart required. We re-read the .env file
     on every check instead of relying on a value cached at import
     time, so flipping the flag takes effect on the very next query.
  3. A second, independent activation path: a runtime flag file
     (KILL_SWITCH.flag). This lets an on-call engineer or an external
     monitoring script trip the switch by touching a file, without
     needing repo/deploy access to edit .env — a common enterprise
     "big red button" pattern.
  4. Fail-safe default: if anything goes wrong reading the flag, we
     err on the side of BLOCKING AI processing, never silently
     allowing it.

Usage (from the Supervisor Agent, before any agent/LLM call):

    from core.kill_switch import KillSwitch, KillSwitchActiveError

    try:
        KillSwitch.enforce()
    except KillSwitchActiveError as e:
        return str(e)   # short-circuit — no LLM/agent calls happen
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from dotenv import load_dotenv

from utils.logger import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_KILL_FLAG_FILE = _PROJECT_ROOT / "KILL_SWITCH.flag"
_ENV_FILE = _PROJECT_ROOT / ".env"


class KillSwitchActiveError(RuntimeError):
    """Raised by KillSwitch.enforce() when AI processing is disabled."""


class KillSwitch:
    """Static/singleton-style controller — no instance state needed."""

    _lock = threading.Lock()

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------
    @staticmethod
    def is_active() -> bool:
        """
        Returns True if AI processing should be blocked right now.
        Checked fresh every call (no caching) for immediate effect.
        """
        try:
            load_dotenv(dotenv_path=_ENV_FILE, override=True)
        except Exception as e:  # fail-safe: treat unreadable .env as "blocked"
            logger.error(f"[KillSwitch] Could not read .env ({e}); failing closed.")
            return True

        env_flag = os.getenv("KILL_SWITCH_ENABLED", "false").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        try:
            file_flag = _KILL_FLAG_FILE.exists()
        except Exception as e:
            logger.error(f"[KillSwitch] Could not check flag file ({e}); failing closed.")
            return True

        return env_flag or file_flag

    @staticmethod
    def status() -> dict:
        return {
            "active": KillSwitch.is_active(),
            "env_flag": os.getenv("KILL_SWITCH_ENABLED", "false"),
            "flag_file_present": _KILL_FLAG_FILE.exists(),
        }

    # ------------------------------------------------------------------
    # CONTROL
    # ------------------------------------------------------------------
    @staticmethod
    def engage(reason: str = "manual activation") -> None:
        """Immediately disable all AI processing via the runtime flag file."""
        with KillSwitch._lock:
            _KILL_FLAG_FILE.write_text(reason)
        logger.warning(f"[KillSwitch] ENGAGED — reason: {reason}")

    @staticmethod
    def disengage() -> None:
        """Re-enable AI processing (removes the runtime flag file only;
        does not touch .env — an operator who set KILL_SWITCH_ENABLED=true
        in .env must also flip that back)."""
        with KillSwitch._lock:
            if _KILL_FLAG_FILE.exists():
                _KILL_FLAG_FILE.unlink()
        logger.info("[KillSwitch] Disengaged (runtime flag cleared).")

    # ------------------------------------------------------------------
    # ENFORCEMENT
    # ------------------------------------------------------------------
    @staticmethod
    def enforce() -> None:
        """Raises KillSwitchActiveError if AI processing is blocked.
        Call this FIRST, before any agent or LLM invocation."""
        if KillSwitch.is_active():
            logger.critical("[KillSwitch] AI processing request BLOCKED.")
            raise KillSwitchActiveError(
                "AI processing is currently disabled by the system kill switch. "
                "Please contact an administrator to re-enable it before "
                "retrying your query."
            )
