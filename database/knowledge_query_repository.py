"""Read-only queries for presenting the Miracle Nikki knowledge base."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from database.database import ensure_database_initialized, get_connection


@dataclass(frozen=True, slots=True)
class EventPeriodView:
    """A published availability period for an event."""

    period_type: str
    start_at: str | None
    end_at: str | None


@dataclass(frozen=True, slots=True)
class EventSuitView:
    """A suit associated with an event."""

    name: str
    is_live2d: bool
    acquisition_method: str | None
    cost_text: str | None
    appearance_status: str = "unknown"


@dataclass(frozen=True, slots=True)
class EventView:
    """All approved knowledge-base information displayed for an event."""

    id: int
    name: str
    official_series: str | None
    event_type: str | None
    description: str | None
    periods: list[EventPeriodView]
    suits: list[EventSuitView]
    event_total_cost: str | None
    live2d_cost: str | None
    data_status: str = "auto"


@dataclass(frozen=True, slots=True)
class SuitPeriodView:
    """One availability period associated with a suit's event."""

    period_type: str
    start_at: str | None
    end_at: str | None


@dataclass(frozen=True, slots=True)
class SuitEventView:
    """An event in which a suit is available, including all its periods."""

    event_name: str
    event_type: str | None
    acquisition_method: str | None
    cost_text: str | None
    periods: list[SuitPeriodView]
    appearance_status: str = "unknown"


@dataclass(frozen=True, slots=True)
class SuitView:
    """All approved knowledge-base information displayed for a suit."""

    id: int
    name: str
    official_name: str | None
    is_live2d: bool
    description: str | None
    events: list[SuitEventView]
    data_status: str = "auto"


@dataclass(frozen=True, slots=True)
class RawPostImageView:
    """One stored raw Facebook image available for administrator assignment."""

    id: int
    image_url: str


@dataclass(frozen=True, slots=True)
class SuitImageCandidate:
    """A suit that belongs to an event being configured."""

    id: int
    name: str


@dataclass(frozen=True, slots=True)
class SuitEditEvent:
    """One event context available when editing a suit's card information."""

    id: int
    name: str
    event_type: str | None
    acquisition_method_id: int | None
    acquisition_method: str | None
    cost_text: str | None
    appearance_status: str = "unknown"


@dataclass(frozen=True, slots=True)
class SuitEditContext:
    """Editable suit data and its most recent event-specific values."""

    suit_id: int
    suit_name: str
    is_live2d: bool
    events: list[SuitEditEvent]


@dataclass(frozen=True, slots=True)
class EventEditContext:
    """Editable event fields used by the administrator event card."""

    event_id: int
    name: str
    content_type: str
    event_status: str | None
    official_series: str | None
    notes: str | None
    start_at: str | None
    end_at: str | None
    event_type_id: int | None
    event_type_name: str | None
    is_visible: bool


class KnowledgeQueryRepository:
    """Provides read-only event and suit lookups for application clients."""

    def __init__(self, database_path: Path | None = None) -> None:
        self._database_path = database_path
        ensure_database_initialized(database_path)

    def _connect(self) -> sqlite3.Connection:
        """Open a query connection; schema initialization happens at startup."""
        return get_connection(self._database_path)

    def get_event_by_name(self, name: str) -> EventView | None:
        """Return an event by its exact name, or ``None`` when it is unknown."""
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT e.id, e.name, e.official_series, et.name, e.description, e.data_status
                FROM events AS e
                LEFT JOIN event_types AS et ON et.id = e.event_type_id
                WHERE e.name = ?
                  AND e.content_type IN ('event', 'suit_event')
                  AND e.is_visible = 1
                """,
                (name.strip(),),
            ).fetchone()
            if row is None:
                return None
            return self._build_event_view(connection, row)
        finally:
            connection.close()

    def get_event_by_id(self, event_id: int) -> EventView | None:
        """Return the current event card data for an administrator refresh."""
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT e.id, e.name, e.official_series, et.name, e.description, e.data_status
                FROM events AS e
                LEFT JOIN event_types AS et ON et.id = e.event_type_id
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
            return self._build_event_view(connection, row) if row is not None else None
        finally:
            connection.close()

    def get_queryable_event_by_id(self, event_id: int) -> EventView | None:
        """Return one visible player-queryable event by its stable identifier."""
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT e.id, e.name, e.official_series, et.name, e.description, e.data_status
                FROM events AS e
                LEFT JOIN event_types AS et ON et.id = e.event_type_id
                WHERE e.id = ?
                  AND e.content_type IN ('event', 'suit_event')
                  AND e.is_visible = 1
                """,
                (event_id,),
            ).fetchone()
            return self._build_event_view(connection, row) if row is not None else None
        finally:
            connection.close()

    def get_events_by_name(self, name: str) -> list[EventView]:
        """Return every visible event with an exact display name."""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT e.id, e.name, e.official_series, et.name, e.description, e.data_status
                FROM events AS e
                LEFT JOIN event_types AS et ON et.id = e.event_type_id
                WHERE e.name = ?
                  AND e.content_type IN ('event', 'suit_event')
                  AND e.is_visible = 1
                ORDER BY e.id
                """,
                (name.strip(),),
            ).fetchall()
            return [self._build_event_view(connection, row) for row in rows]
        finally:
            connection.close()

    def get_event_edit_context(self, event_id: int) -> EventEditContext | None:
        """Read one event and its most recent period for the management UI."""
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT e.id, e.name, e.content_type, e.event_status, e.official_series,
                       e.description, e.event_type_id, et.name, e.is_visible,
                       p.start_at, p.end_at
                FROM events AS e
                LEFT JOIN event_types AS et ON et.id = e.event_type_id
                LEFT JOIN event_periods AS p ON p.id = (
                    SELECT id FROM event_periods WHERE event_id = e.id
                    ORDER BY start_at DESC, id DESC LIMIT 1
                )
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            return EventEditContext(
                event_id=int(row[0]), name=str(row[1]), content_type=str(row[2]),
                event_status=row[3], official_series=row[4], notes=row[5],
                event_type_id=int(row[6]) if row[6] is not None else None,
                event_type_name=row[7], is_visible=bool(row[8]), start_at=row[9], end_at=row[10],
            )
        finally:
            connection.close()

    def get_event_suit_names(self, event_id: int) -> list[str]:
        """Read the current event suit list in display order for a fresh modal."""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT suits.name
                FROM event_suits
                JOIN suits ON suits.id = event_suits.suit_id
                WHERE event_suits.event_id = ?
                ORDER BY event_suits.display_order, event_suits.id
                """,
                (event_id,),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            connection.close()

    def synchronize_event_suits(self, event_id: int, names: list[str]) -> list[str]:
        """Replace an event's suit associations with the supplied ordered names.

        Existing suit records are reused by exact name. Removed lines only remove
        the event relationship; this deliberately leaves possible orphan suits for
        the dedicated cleanup tool.
        """
        ordered_names = list(dict.fromkeys(name.strip() for name in names if name.strip()))
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            current_rows = connection.execute(
                """
                SELECT event_suits.id, suits.id, suits.name
                FROM event_suits
                JOIN suits ON suits.id = event_suits.suit_id
                WHERE event_suits.event_id = ?
                """,
                (event_id,),
            ).fetchall()
            current_by_name = {str(row[2]): (int(row[0]), int(row[1])) for row in current_rows}
            desired_names = set(ordered_names)
            for relationship_id, _suit_id, name in current_rows:
                if str(name) not in desired_names:
                    connection.execute("DELETE FROM event_suits WHERE id = ?", (relationship_id,))

            now = datetime.now(timezone.utc).isoformat()
            for position, name in enumerate(ordered_names):
                current = current_by_name.get(name)
                if current is not None:
                    connection.execute(
                        """
                        UPDATE event_suits
                        SET display_order = ?, data_status = 'verified', updated_via = 'discord_admin'
                        WHERE id = ?
                        """,
                        (position, current[0]),
                    )
                    continue
                suit = connection.execute("SELECT id FROM suits WHERE name = ?", (name,)).fetchone()
                if suit is None:
                    suit_id = int(
                        connection.execute(
                            """
                            INSERT INTO suits (
                                name, created_at, updated_at, data_status, created_via, updated_via
                            ) VALUES (?, ?, ?, 'verified', 'discord_admin', 'discord_admin')
                            """,
                            (name, now, now),
                        ).lastrowid
                    )
                else:
                    suit_id = int(suit[0])
                connection.execute(
                    """
                    INSERT INTO event_suits (
                        event_id, suit_id, display_order, data_status, updated_via
                    ) VALUES (?, ?, ?, 'verified', 'discord_admin')
                    """,
                    (event_id, suit_id, position),
                )

            connection.execute(
                """
                UPDATE events
                SET data_status = 'verified', updated_via = 'discord_admin', updated_at = ?
                WHERE id = ?
                """,
                (now, event_id),
            )
            connection.commit()
            return ordered_names
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_event_suit_details(self, event_id: int, suit_id: int) -> dict[str, object] | None:
        """Load one event-suit relation fresh for the focused suit editor."""
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT suits.name, event_suits.appearance_status, acquisition_methods.name,
                       cost_records.cost_text
                FROM event_suits
                JOIN suits ON suits.id = event_suits.suit_id
                LEFT JOIN acquisition_methods ON acquisition_methods.id = event_suits.acquisition_method_id
                LEFT JOIN cost_records ON cost_records.event_id = event_suits.event_id
                    AND cost_records.suit_id = event_suits.suit_id
                    AND cost_records.cost_scope = 'single_suit'
                WHERE event_suits.event_id = ? AND event_suits.suit_id = ?
                """,
                (event_id, suit_id),
            ).fetchone()
            if row is None:
                return None
            return {"name": row[0], "appearance_status": row[1], "acquisition_method": row[2], "cost_text": row[3]}
        finally:
            connection.close()

    def get_event_suit_details_by_name(self, event_id: int, name: str) -> dict[str, object] | None:
        """Resolve a current event suit by name for the compact select menu."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT suits.id FROM event_suits JOIN suits ON suits.id = event_suits.suit_id WHERE event_suits.event_id = ? AND suits.name = ?",
                (event_id, name),
            ).fetchone()
            if row is None:
                return None
            details = self.get_event_suit_details(event_id, int(row[0]))
            if details is not None:
                details["suit_id"] = int(row[0])
            return details
        finally:
            connection.close()

    def save_event_suit_details(
        self,
        event_id: int,
        original_suit_id: int | None,
        *,
        name: str,
        appearance_status: str | None = None,
        event_type_name: str | None = None,
        acquisition_method: str | None = None,
        cost_text: str | None = None,
    ) -> int:
        """Create or correct one suit relation, including acquisition and cost."""
        if appearance_status is not None and appearance_status not in {"debut", "rerun", "return", "unknown"}:
            raise ValueError("Unsupported appearance status.")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Suit name is required.")
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            now = datetime.now(timezone.utc).isoformat()
            if event_type_name is not None:
                category = event_type_name.strip()
                if not category:
                    event_type_id = None
                else:
                    type_row = connection.execute("SELECT id FROM event_types WHERE name = ?", (category,)).fetchone()
                    event_type_id = int(type_row[0]) if type_row is not None else int(
                        connection.execute("INSERT INTO event_types (name, is_active) VALUES (?, 1)", (category,)).lastrowid
                    )
                connection.execute("UPDATE events SET event_type_id = ?, data_status = 'verified', updated_via = 'discord_admin', updated_at = ? WHERE id = ?", (event_type_id, now, event_id))
            suit = connection.execute("SELECT id FROM suits WHERE name = ?", (normalized_name,)).fetchone()
            if suit is None:
                suit_id = int(connection.execute(
                    "INSERT INTO suits (name, created_at, updated_at, data_status, created_via, updated_via) VALUES (?, ?, ?, 'verified', 'discord_admin', 'discord_admin')",
                    (normalized_name, now, now),
                ).lastrowid)
            else:
                suit_id = int(suit[0])
            method_id: int | None = None
            normalized_method = (acquisition_method or "").strip()
            if normalized_method:
                method = connection.execute("SELECT id FROM acquisition_methods WHERE name = ?", (normalized_method,)).fetchone()
                if method is None:
                    method_id = int(connection.execute("INSERT INTO acquisition_methods (name, is_active) VALUES (?, 1)", (normalized_method,)).lastrowid)
                else:
                    method_id = int(method[0])
            if original_suit_id is not None and original_suit_id != suit_id:
                connection.execute("DELETE FROM event_suits WHERE event_id = ? AND suit_id = ?", (event_id, original_suit_id))
            relation = connection.execute("SELECT id FROM event_suits WHERE event_id = ? AND suit_id = ?", (event_id, suit_id)).fetchone()
            if relation is None:
                position = int(connection.execute("SELECT COALESCE(MAX(display_order) + 1, 0) FROM event_suits WHERE event_id = ?", (event_id,)).fetchone()[0])
                connection.execute(
                    "INSERT INTO event_suits (event_id, suit_id, acquisition_method_id, display_order, appearance_status, data_status, updated_via) VALUES (?, ?, ?, ?, ?, 'verified', 'discord_admin')",
                    (event_id, suit_id, method_id, position, appearance_status or "unknown"),
                )
            else:
                if appearance_status is None:
                    connection.execute(
                        "UPDATE event_suits SET acquisition_method_id = ?, data_status = 'verified', updated_via = 'discord_admin' WHERE id = ?",
                        (method_id, relation[0]),
                    )
                else:
                    connection.execute(
                        "UPDATE event_suits SET acquisition_method_id = ?, appearance_status = ?, data_status = 'verified', updated_via = 'discord_admin' WHERE id = ?",
                        (method_id, appearance_status, relation[0]),
                    )
            cost = connection.execute("SELECT id FROM cost_records WHERE event_id = ? AND suit_id = ? AND cost_scope = 'single_suit'", (event_id, suit_id)).fetchone()
            normalized_cost = (cost_text or "").strip()
            if normalized_cost and cost is None:
                connection.execute("INSERT INTO cost_records (event_id, suit_id, cost_scope, cost_text) VALUES (?, ?, 'single_suit', ?)", (event_id, suit_id, normalized_cost))
            elif normalized_cost and cost is not None:
                connection.execute("UPDATE cost_records SET cost_text = ? WHERE id = ?", (normalized_cost, cost[0]))
            elif cost is not None:
                connection.execute("DELETE FROM cost_records WHERE id = ?", (cost[0],))
            connection.execute("UPDATE events SET data_status = 'verified', updated_via = 'discord_admin', updated_at = ? WHERE id = ?", (now, event_id))
            connection.commit()
            return suit_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_event_info(
        self, event_id: int, event_type_name: str | None, start_at: str, end_at: str, notes: str | None
    ) -> None:
        """Save the small set of event-level fields administrators actually correct."""
        from datetime import datetime as date_time
        from zoneinfo import ZoneInfo

        try:
            start = date_time.strptime(start_at.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Taipei"))
            end = date_time.strptime(end_at.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Taipei"))
        except ValueError as error:
            raise ValueError("時間格式必須為 YYYY-MM-DD HH:mm。") from error
        if end < start:
            raise ValueError("結束時間不得早於開始時間。")
        category = (event_type_name or "").strip()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            if category:
                row = connection.execute("SELECT id FROM event_types WHERE name = ?", (category,)).fetchone()
                if row is None:
                    event_type_id = int(connection.execute("INSERT INTO event_types (name, is_active) VALUES (?, 1)", (category,)).lastrowid)
                else:
                    event_type_id = int(row[0])
            else:
                event_type_id = None
            now = datetime.now(timezone.utc).isoformat()
            connection.execute("UPDATE events SET event_type_id = ?, description = ?, data_status = 'verified', updated_via = 'discord_admin', updated_at = ? WHERE id = ?", (event_type_id, notes or None, now, event_id))
            period = connection.execute("SELECT id FROM event_periods WHERE event_id = ? ORDER BY start_at DESC, id DESC LIMIT 1", (event_id,)).fetchone()
            if period is None:
                connection.execute("INSERT INTO event_periods (event_id, period_type, start_at, end_at, created_at, data_status, updated_via) VALUES (?, 'unknown', ?, ?, ?, 'verified', 'discord_admin')", (event_id, start.isoformat(), end.isoformat(), now))
            else:
                connection.execute("UPDATE event_periods SET start_at = ?, end_at = ?, data_status = 'verified', updated_via = 'discord_admin' WHERE id = ?", (start.isoformat(), end.isoformat(), period[0]))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_event_management(
        self,
        event_id: int,
        *,
        name: str,
        content_type: str,
        event_status: str | None,
        official_series: str | None,
        notes: str | None,
        start_at: str | None,
        end_at: str | None,
        is_visible: bool,
    ) -> None:
        """Persist administrator changes and protect the event from parser updates."""
        if content_type not in {"suit_event", "event", "welfare", "wallpaper", "system", "notice", "other"}:
            raise ValueError("Unsupported content type.")
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                UPDATE events
                SET name = ?, content_type = ?, event_status = ?, official_series = ?,
                    description = ?, is_visible = ?, data_status = 'verified',
                    updated_via = 'discord_admin', updated_at = ?
                WHERE id = ?
                """,
                (name.strip(), content_type, event_status, official_series, notes, int(is_visible), now, event_id),
            )
            period = connection.execute(
                "SELECT id FROM event_periods WHERE event_id = ? ORDER BY start_at DESC, id DESC LIMIT 1",
                (event_id,),
            ).fetchone()
            if period is not None:
                connection.execute(
                    """
                    UPDATE event_periods
                    SET start_at = ?, end_at = ?, data_status = 'verified', updated_via = 'discord_admin'
                    WHERE id = ?
                    """,
                    (start_at, end_at, period[0]),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO event_periods (
                        event_id, period_type, start_at, end_at, created_at,
                        data_status, updated_via
                    ) VALUES (?, 'unknown', ?, ?, ?, 'verified', 'discord_admin')
                    """,
                    (event_id, start_at, end_at, now),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_event_type(self, event_id: int, event_type_id: int | None) -> None:
        self._update_event_field(event_id, "event_type_id", event_type_id)

    def update_event_acquisition_method(self, event_id: int, acquisition_method_id: int | None) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                UPDATE event_suits
                SET acquisition_method_id = ?, data_status = 'verified', updated_via = 'discord_admin'
                WHERE event_id = ?
                """,
                (acquisition_method_id, event_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_event_total_cost(self, event_id: int) -> str | None:
        """Return the current event-wide cost text for the management section."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT cost_text FROM cost_records WHERE event_id = ? AND suit_id IS NULL AND cost_scope = 'event_total'",
                (event_id,),
            ).fetchone()
            return str(row[0]) if row is not None else None
        finally:
            connection.close()

    def update_event_total_cost(self, event_id: int, cost_text: str | None) -> None:
        """Upsert or clear an event-wide cost entered by an administrator."""
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            existing = connection.execute(
                "SELECT id FROM cost_records WHERE event_id = ? AND suit_id IS NULL AND cost_scope = 'event_total'",
                (event_id,),
            ).fetchone()
            normalized = (cost_text or "").strip()
            if normalized and existing is None:
                connection.execute(
                    "INSERT INTO cost_records (event_id, suit_id, cost_scope, cost_text) VALUES (?, NULL, 'event_total', ?)",
                    (event_id, normalized),
                )
            elif normalized and existing is not None:
                connection.execute("UPDATE cost_records SET cost_text = ? WHERE id = ?", (normalized, existing[0]))
            elif existing is not None:
                connection.execute("DELETE FROM cost_records WHERE id = ?", (existing[0],))
            connection.execute(
                "UPDATE events SET data_status = 'verified', updated_via = 'discord_admin', updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), event_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_event_verified(self, event_id: int) -> None:
        """Confirm an event and its current periods/relationships without changing content."""
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            connection.execute("UPDATE events SET data_status = 'verified', updated_via = 'admin' WHERE id = ?", (event_id,))
            connection.execute("UPDATE event_periods SET data_status = 'verified', updated_via = 'admin' WHERE event_id = ?", (event_id,))
            connection.execute("UPDATE event_suits SET data_status = 'verified', updated_via = 'admin' WHERE event_id = ?", (event_id,))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _update_event_field(self, event_id: int, field_name: str, value: object) -> None:
        if field_name not in {"event_type_id"}:
            raise ValueError("Unsupported event field.")
        connection = self._connect()
        try:
            connection.execute(
                f"UPDATE events SET {field_name} = ?, data_status = 'verified', updated_via = 'discord_admin' WHERE id = ?",
                (value, event_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_suit_by_name(self, name: str) -> SuitView | None:
        """Return a suit by its exact name, or ``None`` when it is unknown."""
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT id, name, official_name, is_live2d, description, data_status
                FROM suits
                WHERE name = ?
                """,
                (name.strip(),),
            ).fetchone()
            if row is None:
                return None
            suit_id, suit_name, official_name, is_live2d, description, data_status = row
            event_rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.name,
                    et.name,
                    am.name,
                    single_suit_cost.cost_text,
                    es.appearance_status,
                    event_total_cost.cost_text,
                    (
                        SELECT COUNT(*)
                        FROM event_suits AS event_suit_count
                        WHERE event_suit_count.event_id = e.id
                    ) AS event_suit_count,
                    (
                        SELECT MIN(event_periods.start_at)
                        FROM event_periods
                        WHERE event_periods.event_id = e.id
                    ) AS first_period_start,
                    (
                        SELECT MAX(event_periods.start_at)
                        FROM event_periods
                        WHERE event_periods.event_id = e.id
                    ) AS latest_period_start
                FROM event_suits AS es
                JOIN events AS e ON e.id = es.event_id
                LEFT JOIN event_types AS et ON et.id = e.event_type_id
                LEFT JOIN acquisition_methods AS am ON am.id = es.acquisition_method_id
                LEFT JOIN cost_records AS single_suit_cost
                    ON single_suit_cost.event_id = es.event_id
                    AND single_suit_cost.suit_id = es.suit_id
                    AND single_suit_cost.cost_scope = 'single_suit'
                LEFT JOIN cost_records AS event_total_cost
                    ON event_total_cost.event_id = es.event_id
                    AND event_total_cost.suit_id IS NULL
                    AND event_total_cost.cost_scope = 'event_total'
                WHERE es.suit_id = ?
                ORDER BY latest_period_start DESC, e.updated_at DESC, es.display_order
                """,
                (suit_id,),
            ).fetchall()
            events = []
            for (
                event_id,
                event_name,
                event_type,
                acquisition_method,
                single_suit_cost,
                appearance_status,
                event_total_cost,
                event_suit_count,
                _first_period_start,
                _latest_period_start,
            ) in event_rows:
                period_rows = connection.execute(
                    """
                    SELECT period_type, start_at, end_at
                    FROM event_periods
                    WHERE event_id = ?
                    ORDER BY start_at IS NULL, start_at ASC, id ASC
                    """,
                    (event_id,),
                ).fetchall()
                cost_text = single_suit_cost
                if cost_text is None and event_suit_count == 1:
                    cost_text = event_total_cost
                events.append(
                    SuitEventView(
                        event_name=str(event_name),
                        event_type=event_type,
                        acquisition_method=acquisition_method,
                        cost_text=cost_text,
                        periods=[SuitPeriodView(*period) for period in period_rows],
                        appearance_status=str(appearance_status or "unknown"),
                    )
                )
            return SuitView(
                id=int(suit_id),
                name=str(suit_name),
                official_name=official_name,
                is_live2d=bool(is_live2d),
                description=description,
                events=events,
                data_status=str(data_status),
            )
        finally:
            connection.close()

    def search_event_names(self, query: str, limit: int = 5) -> list[str]:
        """Return a small list of matching event names for command suggestions."""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT name FROM events
                WHERE name LIKE ? AND content_type IN ('event', 'suit_event') AND is_visible = 1
                ORDER BY name LIMIT ?
                """,
                (f"%{query.strip()}%", limit),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            connection.close()

    def search_event_options(
        self, query: str, limit: int = 5
    ) -> list[tuple[int, str, str | None]]:
        """Return distinct autocomplete options keyed by the event primary key."""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT e.id, e.name,
                       (
                           SELECT start_at
                           FROM event_periods
                           WHERE event_id = e.id
                           ORDER BY start_at IS NULL, start_at DESC, id DESC
                           LIMIT 1
                       ) AS latest_start_at
                FROM events AS e
                WHERE e.name LIKE ?
                  AND e.content_type IN ('event', 'suit_event')
                  AND e.is_visible = 1
                ORDER BY e.name, latest_start_at DESC, e.id DESC
                LIMIT ?
                """,
                (f"%{query.strip()}%", limit),
            ).fetchall()
            return [
                (int(event_id), str(name), str(start_at) if start_at else None)
                for event_id, name, start_at in rows
            ]
        finally:
            connection.close()

    def search_suit_names(self, query: str, limit: int = 5) -> list[str]:
        """Return a small list of matching suit names for command suggestions."""
        return self._search_names("suits", query, limit)

    def get_announcement_image_for_event(self, event_name: str) -> str | None:
        """Return the first stored raw-announcement image matching an event name.

        This is a display-only fallback until the knowledge base has dedicated
        event or suit image fields.
        """
        connection = self._connect()
        try:
            try:
                row = connection.execute(
                    """
                    SELECT raw_post_images.image_url
                    FROM raw_posts
                    JOIN raw_post_images ON raw_post_images.raw_post_id = raw_posts.id
                    WHERE raw_posts.content LIKE ?
                    ORDER BY raw_posts.published_at DESC, raw_post_images.position ASC
                    LIMIT 1
                    """,
                    (f"%{event_name.strip()}%",),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
            return str(row[0]) if row else None
        finally:
            connection.close()

    def get_announcement_image_for_event_id(self, event_id: int) -> str | None:
        """Return the first image from the raw post that created this event."""
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT raw_post_images.image_url
                FROM events
                JOIN raw_post_images
                    ON raw_post_images.raw_post_id = events.source_raw_post_id
                WHERE events.id = ?
                ORDER BY raw_post_images.position ASC, raw_post_images.id ASC
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            connection.close()

    def get_announcement_image_for_events(self, event_names: list[str]) -> str | None:
        """Return the first available announcement image among related events."""
        for event_name in event_names:
            image_url = self.get_announcement_image_for_event(event_name)
            if image_url:
                return image_url
        return None

    def get_primary_image_for_suit(self, suit_id: int) -> str | None:
        """Return the explicitly assigned primary image for a suit, if any."""
        connection = self._connect()
        try:
            try:
                row = connection.execute(
                    """
                    SELECT raw_post_images.image_url
                    FROM suit_images
                    JOIN raw_post_images ON raw_post_images.id = suit_images.raw_post_image_id
                    WHERE suit_images.suit_id = ? AND suit_images.is_primary = 1
                    ORDER BY suit_images.display_order, suit_images.id
                    LIMIT 1
                    """,
                    (suit_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
            return str(row[0]) if row else None
        finally:
            connection.close()

    def get_display_image_for_suit(self, suit_id: int) -> str | None:
        """Use an explicit suit image, or a safe one-suit activity fallback."""
        primary_image = self.get_primary_image_for_suit(suit_id)
        if primary_image:
            return primary_image

        connection = self._connect()
        try:
            try:
                rows = connection.execute(
                    """
                    SELECT e.name
                    FROM event_suits AS es
                    JOIN events AS e ON e.id = es.event_id
                    WHERE es.suit_id = ?
                      AND (
                          SELECT COUNT(*)
                          FROM event_suits AS event_suit_count
                          WHERE event_suit_count.event_id = es.event_id
                      ) = 1
                    ORDER BY (
                        SELECT MAX(event_periods.start_at)
                        FROM event_periods
                        WHERE event_periods.event_id = e.id
                    ) DESC, e.updated_at DESC
                    """,
                    (suit_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                return None
        finally:
            connection.close()

        for (event_name,) in rows:
            image_url = self.get_announcement_image_for_event(str(event_name))
            if image_url:
                return image_url
        return None

    def get_raw_images_for_event(self, event_id: int) -> list[RawPostImageView]:
        """List stored announcement images for the event's source raw post."""
        connection = self._connect()
        try:
            try:
                rows = connection.execute(
                    """
                    SELECT raw_post_images.id, raw_post_images.image_url
                    FROM events
                    JOIN raw_post_images
                      ON raw_post_images.raw_post_id = events.source_raw_post_id
                    WHERE events.id = ?
                      AND events.source_raw_post_id IS NOT NULL
                    ORDER BY raw_post_images.position ASC, raw_post_images.id ASC
                    """,
                    (event_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
            return [RawPostImageView(int(image_id), str(image_url)) for image_id, image_url in rows]
        finally:
            connection.close()

    def get_event_suits_for_image_assignment(self, event_id: int) -> list[SuitImageCandidate]:
        """Return suits eligible to receive one of an event's raw images."""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT suits.id, suits.name
                FROM event_suits
                JOIN suits ON suits.id = event_suits.suit_id
                WHERE event_suits.event_id = ?
                ORDER BY event_suits.display_order, event_suits.id
                """,
                (event_id,),
            ).fetchall()
            return [SuitImageCandidate(int(suit_id), str(name)) for suit_id, name in rows]
        finally:
            connection.close()

    def assign_primary_image_to_suit(self, suit_id: int, raw_post_image_id: int) -> None:
        """Assign a stored raw image as the suit's sole primary image atomically."""
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            connection.execute(
                "UPDATE suit_images SET is_primary = 0 WHERE suit_id = ?", (suit_id,)
            )
            next_position = connection.execute(
                "SELECT COALESCE(MAX(display_order) + 1, 0) FROM suit_images WHERE suit_id = ?",
                (suit_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO suit_images (suit_id, raw_post_image_id, display_order, is_primary)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(suit_id, raw_post_image_id)
                DO UPDATE SET is_primary = 1
                """,
                (suit_id, raw_post_image_id, next_position),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_suit_edit_context(self, suit_id: int) -> SuitEditContext | None:
        """Return a suit and its event-specific values for the Discord edit UI."""
        connection = self._connect()
        try:
            suit_row = connection.execute(
                "SELECT id, name, is_live2d FROM suits WHERE id = ?", (suit_id,)
            ).fetchone()
            if suit_row is None:
                return None
            event_rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.name,
                    event_types.name,
                    event_suits.acquisition_method_id,
                    acquisition_methods.name,
                    cost_records.cost_text,
                    event_suits.appearance_status,
                    (
                        SELECT MAX(event_periods.start_at)
                        FROM event_periods
                        WHERE event_periods.event_id = e.id
                    ) AS latest_period_start
                FROM event_suits
                JOIN events AS e ON e.id = event_suits.event_id
                LEFT JOIN event_types ON event_types.id = e.event_type_id
                LEFT JOIN acquisition_methods
                    ON acquisition_methods.id = event_suits.acquisition_method_id
                LEFT JOIN cost_records
                    ON cost_records.event_id = event_suits.event_id
                    AND cost_records.suit_id = event_suits.suit_id
                    AND cost_records.cost_scope = 'single_suit'
                WHERE event_suits.suit_id = ?
                ORDER BY latest_period_start DESC, e.updated_at DESC, event_suits.display_order
                """,
                (suit_id,),
            ).fetchall()
            events = [
                SuitEditEvent(
                    id=int(event_id),
                    name=str(event_name),
                    event_type=event_type,
                    acquisition_method_id=int(acquisition_method_id)
                    if acquisition_method_id is not None
                    else None,
                    acquisition_method=acquisition_method,
                    cost_text=cost_text,
                    appearance_status=str(appearance_status or "unknown"),
                )
                for (
                    event_id,
                    event_name,
                    event_type,
                    acquisition_method_id,
                    acquisition_method,
                    cost_text,
                    appearance_status,
                    _latest_period_start,
                ) in event_rows
            ]
            return SuitEditContext(
                suit_id=int(suit_row[0]),
                suit_name=str(suit_row[1]),
                is_live2d=bool(suit_row[2]),
                events=events,
            )
        finally:
            connection.close()

    def get_acquisition_method_options(self) -> list[tuple[int, str]]:
        """Return active acquisition methods for Discord selection controls."""
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, name FROM acquisition_methods WHERE is_active = 1 ORDER BY id"
            ).fetchall()
            return [(int(method_id), str(name)) for method_id, name in rows]
        finally:
            connection.close()

    def update_suit_card_data(
        self,
        suit_id: int,
        event_id: int,
        acquisition_method_id: int | None,
        cost_text: str | None,
        is_live2d: bool,
    ) -> None:
        """Update editable card data while enforcing the Live2D activity rule."""
        connection = self._connect()
        try:
            event_row = connection.execute(
                """
                SELECT event_types.name
                FROM events
                LEFT JOIN event_types ON event_types.id = events.event_type_id
                WHERE events.id = ?
                """,
                (event_id,),
            ).fetchone()
            if event_row is None:
                raise ValueError("找不到套裝所屬活動。")
            if is_live2d and event_row[0] not in {"故事套裝", "大閣"}:
                raise ValueError("只有大閣或故事套裝可設定 Live2D。")

            connection.execute("BEGIN")
            connection.execute(
                "UPDATE suits SET is_live2d = ?, data_status = 'verified', updated_via = 'admin' WHERE id = ?", (int(is_live2d), suit_id)
            )
            connection.execute(
                """
                UPDATE event_suits
                SET acquisition_method_id = ?, data_status = 'verified', updated_via = 'admin'
                WHERE event_id = ? AND suit_id = ?
                """,
                (acquisition_method_id, event_id, suit_id),
            )
            if cost_text:
                cost_row = connection.execute(
                    """
                    SELECT id FROM cost_records
                    WHERE event_id = ? AND suit_id = ? AND cost_scope = 'single_suit'
                    """,
                    (event_id, suit_id),
                ).fetchone()
                if cost_row is None:
                    connection.execute(
                        """
                        INSERT INTO cost_records (event_id, suit_id, cost_scope, cost_text)
                        VALUES (?, ?, 'single_suit', ?)
                        """,
                        (event_id, suit_id, cost_text),
                    )
                else:
                    connection.execute(
                        "UPDATE cost_records SET cost_text = ? WHERE id = ?",
                        (cost_text, cost_row[0]),
                    )
            else:
                connection.execute(
                    """
                    DELETE FROM cost_records
                    WHERE event_id = ? AND suit_id = ? AND cost_scope = 'single_suit'
                    """,
                    (event_id, suit_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_suit_verified(self, suit_id: int) -> None:
        """Confirm a suit and its event relations from the suit management card."""
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            connection.execute("UPDATE suits SET data_status = 'verified', updated_via = 'discord_admin' WHERE id = ?", (suit_id,))
            connection.execute("UPDATE event_suits SET data_status = 'verified', updated_via = 'discord_admin' WHERE suit_id = ?", (suit_id,))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _search_names(self, table: str, query: str, limit: int) -> list[str]:
        if table not in {"events", "suits"}:
            raise ValueError("Unsupported knowledge-base table.")
        connection = self._connect()
        try:
            rows = connection.execute(
                f"SELECT name FROM {table} WHERE name LIKE ? ORDER BY name LIMIT ?",
                (f"%{query.strip()}%", limit),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            connection.close()

    def _build_event_view(
        self, connection: sqlite3.Connection, event_row: tuple[object, ...]
    ) -> EventView:
        event_id, name, official_series, event_type, description, data_status = event_row
        period_rows = connection.execute(
            """
            SELECT period_type, start_at, end_at
            FROM event_periods
            WHERE event_id = ?
            ORDER BY start_at IS NULL, start_at ASC, id ASC
            """,
            (event_id,),
        ).fetchall()
        suit_rows = connection.execute(
            """
            SELECT s.name, s.is_live2d, am.name, cr.cost_text, es.appearance_status
            FROM event_suits AS es
            JOIN suits AS s ON s.id = es.suit_id
            LEFT JOIN acquisition_methods AS am ON am.id = es.acquisition_method_id
            LEFT JOIN cost_records AS cr
                ON cr.event_id = es.event_id
                AND cr.suit_id = es.suit_id
                AND cr.cost_scope = 'single_suit'
            WHERE es.event_id = ?
            ORDER BY es.display_order, es.id
            """,
            (event_id,),
        ).fetchall()
        costs = {
            str(scope): str(cost_text)
            for scope, cost_text in connection.execute(
                """
                SELECT cost_scope, cost_text
                FROM cost_records
                WHERE event_id = ? AND suit_id IS NULL
                """,
                (event_id,),
            ).fetchall()
        }
        return EventView(
            id=int(event_id),
            name=str(name),
            official_series=official_series,
            event_type=event_type,
            description=description,
            periods=[EventPeriodView(*period) for period in period_rows],
            suits=[
                EventSuitView(
                    name=str(suit_name),
                    is_live2d=bool(is_live2d),
                    acquisition_method=acquisition_method,
                    cost_text=cost_text,
                    appearance_status=str(appearance_status or "unknown"),
                )
                for suit_name, is_live2d, acquisition_method, cost_text, appearance_status in suit_rows
            ],
            event_total_cost=costs.get("event_total"),
            live2d_cost=costs.get("live2d"),
            data_status=str(data_status),
        )
