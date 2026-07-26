"""In-memory, guild-scoped cooldown state for Ambient Nikki v1."""

from __future__ import annotations

from datetime import datetime, timedelta


class AmbientNikkiState:
    """Cooldown is intentionally reset by a bot restart and has no database state."""

    def __init__(self) -> None:
        self._last_triggered_at: dict[int, datetime] = {}

    def is_cooling_down(self, guild_id: int, now: datetime, cooldown_minutes: int) -> bool:
        previous = self._last_triggered_at.get(guild_id)
        return previous is not None and now - previous < timedelta(minutes=cooldown_minutes)

    def record_success(self, guild_id: int, now: datetime) -> None:
        self._last_triggered_at[guild_id] = now
