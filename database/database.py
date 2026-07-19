"""SQLite connection and schema helpers."""

import sqlite3
import threading
from pathlib import Path

from database.announcement_identity import canonical_announcement_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "database" / "database.db"
SQLITE_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30_000
_INITIALIZED_DATABASES: set[Path] = set()
_INITIALIZATION_LOCK = threading.Lock()


def get_connection(database_path: Path | None = None) -> sqlite3.Connection:
    """Open a short-lived SQLite connection configured for concurrent callers.

    Schema setup intentionally does not happen here.  Repositories use this helper
    for normal reads and transactions, while :func:`init_database` owns startup
    initialization and WAL configuration.
    """
    path = database_path or DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return connection


def ensure_database_initialized(database_path: Path | None = None) -> None:
    """Initialize a database path once when a standalone repository is used.

    Application entry points call :func:`init_database` eagerly.  This small
    compatibility guard keeps repository APIs usable by scripts and tests without
    restoring DDL to their per-operation ``_connect`` methods.
    """
    path = (database_path or DATABASE_PATH).resolve()
    with _INITIALIZATION_LOCK:
        if path in _INITIALIZED_DATABASES:
            return
        init_database(path)
        _INITIALIZED_DATABASES.add(path)


def initialize_raw_tables(connection: sqlite3.Connection) -> None:
    """Create source-agnostic raw post tables without modifying existing rows."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS raw_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'facebook',
            source_post_id TEXT NOT NULL,
            url TEXT NOT NULL,
            content TEXT NOT NULL,
            published_at TEXT,
            scraped_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            parse_status TEXT NOT NULL DEFAULT 'pending',
            parse_error TEXT,
            content_hash TEXT,
            metadata_json TEXT,
            UNIQUE(source, source_post_id)
        );

        CREATE TABLE IF NOT EXISTS raw_post_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_post_id INTEGER NOT NULL,
            image_url TEXT NOT NULL,
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE,
            UNIQUE(raw_post_id, image_url)
        );

        CREATE TABLE IF NOT EXISTS raw_post_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_post_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            source_post_id TEXT NOT NULL,
            url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE,
            UNIQUE(source, source_post_id),
            UNIQUE(source, url)
        );

        CREATE INDEX IF NOT EXISTS idx_raw_posts_url ON raw_posts(url);
        CREATE INDEX IF NOT EXISTS idx_raw_posts_published_at ON raw_posts(published_at);
        CREATE INDEX IF NOT EXISTS idx_raw_posts_parse_status ON raw_posts(parse_status);
        CREATE INDEX IF NOT EXISTS idx_raw_post_aliases_raw_post_id
            ON raw_post_aliases(raw_post_id);
        """
    )
    raw_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(raw_posts)").fetchall()
    }
    if "metadata_json" not in raw_columns:
        connection.execute("ALTER TABLE raw_posts ADD COLUMN metadata_json TEXT")
    connection.commit()


def initialize_announcement_queue_tables(connection: sqlite3.Connection) -> None:
    """Create durable announcement queue state without changing legacy deliveries."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS announcement_queue_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            initialized_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS announcement_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_post_id INTEGER,
            post_url TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'sending', 'sent', 'skipped', 'failed')),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            sent_at TEXT,
            FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_announcement_jobs_status_created
            ON announcement_jobs(status, created_at);
        """
    )
    connection.commit()
    _migrate_announcement_jobs_to_stable_identity(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_announcement_jobs_raw_post_id "
        "ON announcement_jobs(raw_post_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_announcement_jobs_status_created "
        "ON announcement_jobs(status, created_at)"
    )
    connection.commit()


def _migrate_announcement_jobs_to_stable_identity(connection: sqlite3.Connection) -> None:
    """Preserve queue states while replacing volatile raw IDs as the job key."""
    columns = {
        str(row[1]): bool(row[3])
        for row in connection.execute("PRAGMA table_info(announcement_jobs)")
    }
    foreign_keys = connection.execute("PRAGMA foreign_key_list(announcement_jobs)").fetchall()
    uses_set_null = any(
        row[2] == "raw_posts" and str(row[6]).upper() == "SET NULL"
        for row in foreign_keys
    )
    if "post_url" in columns and not columns.get("raw_post_id", True) and uses_set_null:
        return

    rows = connection.execute(
        """
        SELECT j.id, j.raw_post_id, r.url, j.status, j.attempt_count, j.last_error,
               j.created_at, j.updated_at, j.sent_at
        FROM announcement_jobs AS j
        LEFT JOIN raw_posts AS r ON r.id = j.raw_post_id
        ORDER BY j.id
        """
    ).fetchall()
    priority = {"sent": 5, "skipped": 4, "failed": 3, "sending": 2, "pending": 1}
    retained: dict[str, tuple[object, ...]] = {}
    for row in rows:
        post_url = canonical_announcement_url(str(row[2])) if row[2] else f"orphaned-job:{row[0]}"
        existing = retained.get(post_url)
        if existing is None or priority.get(str(row[3]), 0) > priority.get(str(existing[3]), 0):
            retained[post_url] = (*row[:2], post_url, *row[3:])

    foreign_keys_enabled = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    if foreign_keys_enabled:
        connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN")
        connection.execute(
            """
            CREATE TABLE announcement_jobs_rebuilt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_post_id INTEGER,
                post_url TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sending', 'sent', 'skipped', 'failed')),
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT,
                FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id) ON DELETE SET NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO announcement_jobs_rebuilt (
                id, raw_post_id, post_url, status, attempt_count, last_error,
                created_at, updated_at, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            retained.values(),
        )
        connection.execute("DROP TABLE announcement_jobs")
        connection.execute("ALTER TABLE announcement_jobs_rebuilt RENAME TO announcement_jobs")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if foreign_keys_enabled:
            connection.execute("PRAGMA foreign_keys = ON")


def initialize_parse_draft_tables(connection: sqlite3.Connection) -> None:
    """Create parser draft tables without touching the knowledge-base schema."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS parse_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_post_id INTEGER NOT NULL,
            parser_version TEXT NOT NULL,
            section_index INTEGER NOT NULL DEFAULT 1,
            section_heading TEXT,
            normalized_heading TEXT,
            section_start_line INTEGER NOT NULL DEFAULT 1,
            section_end_line INTEGER NOT NULL DEFAULT 1,
            section_hash TEXT NOT NULL DEFAULT '',
            splitter_version TEXT NOT NULL DEFAULT 'whole-post-v0',
            status TEXT NOT NULL DEFAULT 'pending',
            title TEXT,
            event_name_candidate TEXT,
            official_series_candidate TEXT,
            period_type_candidate TEXT,
            start_at_candidate TEXT,
            end_at_candidate TEXT,
            player_category_candidate TEXT,
            acquisition_method_candidate TEXT,
            confidence REAL,
            parser_notes TEXT,
            review_notes TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE,
            UNIQUE(raw_post_id, section_hash, splitter_version, parser_version)
        );

        CREATE TABLE IF NOT EXISTS parse_draft_suits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parse_draft_id INTEGER NOT NULL,
            suit_name_candidate TEXT NOT NULL,
            position INTEGER NOT NULL,
            confidence REAL,
            notes TEXT,
            FOREIGN KEY (parse_draft_id) REFERENCES parse_drafts(id) ON DELETE CASCADE,
            UNIQUE(parse_draft_id, position)
        );

        CREATE INDEX IF NOT EXISTS idx_parse_drafts_status ON parse_drafts(status);
        CREATE INDEX IF NOT EXISTS idx_parse_drafts_raw_post_id ON parse_drafts(raw_post_id);
        """
    )
    if not _column_exists(connection, "parse_drafts", "content_type_candidate"):
        connection.execute(
            "ALTER TABLE parse_drafts ADD COLUMN content_type_candidate TEXT NOT NULL DEFAULT 'other'"
        )
    _migrate_parse_drafts_to_section_identity(connection)
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_parse_drafts_section_identity
            ON parse_drafts(raw_post_id, section_hash, splitter_version, parser_version);
        CREATE INDEX IF NOT EXISTS idx_parse_drafts_section_hash ON parse_drafts(section_hash);
        """
    )
    connection.commit()


def _parse_drafts_has_legacy_identity(connection: sqlite3.Connection) -> bool:
    """Return whether the pre-section unique key is still present."""
    for index in connection.execute("PRAGMA index_list(parse_drafts)").fetchall():
        if not index[2]:
            continue
        columns = [row[2] for row in connection.execute(f"PRAGMA index_info({index[1]})").fetchall()]
        if columns == ["raw_post_id", "parser_version"]:
            return True
    return False


def _migrate_parse_drafts_to_section_identity(connection: sqlite3.Connection) -> None:
    """Preserve legacy draft rows while replacing the old whole-post unique key."""
    if not _parse_drafts_has_legacy_identity(connection):
        return

    from content.section_splitter import calculate_section_hash

    rows = connection.execute("SELECT * FROM parse_drafts ORDER BY id").fetchall()
    columns = [item[0] for item in connection.execute("SELECT * FROM parse_drafts LIMIT 0").description]
    legacy_rows = [dict(zip(columns, row, strict=True)) for row in rows]
    foreign_keys_enabled = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    if foreign_keys_enabled:
        connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN")
        connection.executescript(
            """
            CREATE TABLE parse_drafts_sectioned (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_post_id INTEGER NOT NULL,
                parser_version TEXT NOT NULL,
                section_index INTEGER NOT NULL DEFAULT 1,
                section_heading TEXT,
                normalized_heading TEXT,
                section_start_line INTEGER NOT NULL DEFAULT 1,
                section_end_line INTEGER NOT NULL DEFAULT 1,
                section_hash TEXT NOT NULL DEFAULT '',
                splitter_version TEXT NOT NULL DEFAULT 'whole-post-v0',
                status TEXT NOT NULL DEFAULT 'pending',
                title TEXT,
                content_type_candidate TEXT NOT NULL DEFAULT 'other',
                event_name_candidate TEXT,
                official_series_candidate TEXT,
                period_type_candidate TEXT,
                start_at_candidate TEXT,
                end_at_candidate TEXT,
                player_category_candidate TEXT,
                acquisition_method_candidate TEXT,
                confidence REAL,
                parser_notes TEXT,
                review_notes TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE,
                UNIQUE(raw_post_id, section_hash, splitter_version, parser_version)
            );
            """
        )
        for row in legacy_rows:
            content_row = connection.execute("SELECT content FROM raw_posts WHERE id = ?", (row["raw_post_id"],)).fetchone()
            content = str(content_row[0]) if content_row else ""
            section_hash = calculate_section_hash(None, content)
            line_count = max(1, len(content.replace("\r\n", "\n").replace("\r", "\n").split("\n")))
            connection.execute(
                """
                INSERT INTO parse_drafts_sectioned (
                    id, raw_post_id, parser_version, section_index, section_heading, normalized_heading,
                    section_start_line, section_end_line, section_hash, splitter_version, status, title,
                    content_type_candidate, event_name_candidate, official_series_candidate,
                    period_type_candidate, start_at_candidate, end_at_candidate, player_category_candidate,
                    acquisition_method_candidate, confidence, parser_notes, review_notes, error_message,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 1, NULL, NULL, 1, ?, ?, 'whole-post-v0', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["raw_post_id"], row["parser_version"], line_count, section_hash,
                    row["status"], row["title"], row.get("content_type_candidate", "other"),
                    row["event_name_candidate"], row["official_series_candidate"], row["period_type_candidate"],
                    row["start_at_candidate"], row["end_at_candidate"], row["player_category_candidate"],
                    row["acquisition_method_candidate"], row["confidence"], row["parser_notes"],
                    row["review_notes"], row["error_message"], row["created_at"], row["updated_at"],
                ),
            )
        connection.execute("DROP TABLE parse_drafts")
        connection.execute("ALTER TABLE parse_drafts_sectioned RENAME TO parse_drafts")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if foreign_keys_enabled:
            connection.execute("PRAGMA foreign_keys = ON")


def initialize_knowledge_base_tables(connection: sqlite3.Connection) -> None:
    """Create the approved-data knowledge-base tables."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS event_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS acquisition_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            official_series TEXT,
            event_type_id INTEGER,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_section_hash TEXT,
            source_splitter_version TEXT,
            FOREIGN KEY (event_type_id) REFERENCES event_types(id)
        );

        CREATE TABLE IF NOT EXISTS event_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            period_type TEXT NOT NULL,
            start_at TEXT,
            end_at TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS suits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            official_name TEXT,
            is_live2d INTEGER NOT NULL DEFAULT 0,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS event_suits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            suit_id INTEGER NOT NULL,
            acquisition_method_id INTEGER,
            display_order INTEGER NOT NULL,
            notes TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
            FOREIGN KEY (suit_id) REFERENCES suits(id) ON DELETE CASCADE,
            FOREIGN KEY (acquisition_method_id) REFERENCES acquisition_methods(id),
            UNIQUE(event_id, suit_id)
        );

        CREATE TABLE IF NOT EXISTS cost_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            suit_id INTEGER,
            cost_scope TEXT NOT NULL,
            cost_text TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
            FOREIGN KEY (suit_id) REFERENCES suits(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS suit_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suit_id INTEGER NOT NULL,
            raw_post_image_id INTEGER,
            image_url TEXT,
            display_order INTEGER NOT NULL DEFAULT 0,
            is_primary INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (suit_id) REFERENCES suits(id) ON DELETE CASCADE,
            FOREIGN KEY (raw_post_image_id) REFERENCES raw_post_images(id) ON DELETE CASCADE,
            CHECK (raw_post_image_id IS NOT NULL OR image_url IS NOT NULL),
            UNIQUE(suit_id, raw_post_image_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_suit_images_one_primary
            ON suit_images(suit_id) WHERE is_primary = 1;
        CREATE INDEX IF NOT EXISTS idx_suit_images_suit_id
            ON suit_images(suit_id);

        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            diamond_cost TEXT,
            event_id INTEGER UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS series_contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            suit_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('main', 'live2d', 'minor', 'frame', 'other')),
            display_order INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE,
            FOREIGN KEY (suit_id) REFERENCES suits(id) ON DELETE CASCADE,
            UNIQUE(series_id, suit_id)
        );

        CREATE INDEX IF NOT EXISTS idx_series_name ON series(name);
        CREATE INDEX IF NOT EXISTS idx_series_contents_order
            ON series_contents(series_id, display_order, id);

        CREATE TABLE IF NOT EXISTS series_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE,
            UNIQUE(series_id, label)
        );

        CREATE INDEX IF NOT EXISTS idx_series_periods_order
            ON series_periods(series_id, display_order, id);
        """
    )
    _migrate_suit_images_to_shared_urls(connection)
    _migrate_series_contents_to_suit_links(connection)
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_suit_images_manual_url "
        "ON suit_images(suit_id, image_url) WHERE image_url IS NOT NULL"
    )
    _initialize_knowledge_provenance_columns(connection)
    _synchronize_existing_series_events(connection)
    # Earlier databases used ``events.name`` as a unique key.  Activity names are
    # display data, however: separate official posts can legitimately have the
    # same name.  Preserve all rows while removing that legacy uniqueness rule.
    _migrate_events_name_unique_constraint(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_source_raw_post_id "
        "ON events(source_raw_post_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_section_source "
        "ON events(source_raw_post_id, source_section_hash, source_splitter_version)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_events_section_source "
        "ON events(source_raw_post_id, source_section_hash, source_splitter_version) "
        "WHERE source_raw_post_id IS NOT NULL AND source_section_hash IS NOT NULL "
        "AND source_splitter_version IS NOT NULL"
    )
    connection.commit()


def _synchronize_existing_series_events(connection: sqlite3.Connection) -> None:
    """Backfill one standard Event graph for each fixed Series without raw-post data."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    rows = connection.execute(
        "SELECT id, name, category, notes, diamond_cost, event_id FROM series ORDER BY id"
    ).fetchall()
    for series_id, name, category, notes, diamond_cost, event_id in rows:
        type_id = None
        if category:
            row = connection.execute("SELECT id FROM event_types WHERE name = ?", (category,)).fetchone()
            type_id = int(row[0]) if row else int(
                connection.execute("INSERT INTO event_types (name, is_active) VALUES (?, 1)", (category,)).lastrowid
            )
        event_row = connection.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone() if event_id else None
        if event_row is None:
            event_id = int(connection.execute(
                """
                INSERT INTO events (name, official_series, event_type_id, description, created_at, updated_at,
                    content_type, is_visible, data_status, created_via, updated_via)
                VALUES (?, ?, ?, ?, ?, ?, 'event', 1, 'verified', 'series', 'series')
                """,
                (name, name, type_id, notes, now, now),
            ).lastrowid)
            connection.execute("UPDATE series SET event_id = ? WHERE id = ?", (event_id, series_id))
        else:
            connection.execute(
                """
                UPDATE events
                SET name = ?, official_series = ?, event_type_id = ?, description = ?,
                    updated_at = ?, updated_via = 'series'
                WHERE id = ?
                """,
                (name, name, type_id, notes, now, event_id),
            )
        _sync_series_event_children(connection, int(series_id), int(event_id), diamond_cost, now)


def _sync_series_event_children(
    connection: sqlite3.Connection, series_id: int, event_id: int, diamond_cost: object, now: str
) -> None:
    """Mirror Series maintenance records into the Event graph used by Discord."""
    connection.execute("DELETE FROM event_suits WHERE event_id = ?", (event_id,))
    content_rows = connection.execute(
        "SELECT suit_id, type, display_order FROM series_contents WHERE series_id = ? ORDER BY display_order, id",
        (series_id,),
    ).fetchall()
    for suit_id, content_type, display_order in content_rows:
        connection.execute(
            """
            INSERT INTO event_suits (event_id, suit_id, display_order, content_type, appearance_status,
                data_status, updated_via)
            VALUES (?, ?, ?, ?, 'unknown', 'verified', 'series')
            """,
            (event_id, suit_id, display_order, content_type),
        )
    connection.execute("DELETE FROM event_periods WHERE event_id = ?", (event_id,))
    for position, (label,) in enumerate(connection.execute(
        "SELECT label FROM series_periods WHERE series_id = ? ORDER BY display_order, id", (series_id,)
    )):
        connection.execute(
            """
            INSERT INTO event_periods (event_id, period_type, notes, created_at, data_status, updated_via)
            VALUES (?, 'unknown', ?, ?, 'verified', 'series')
            """,
            (event_id, label, now),
        )
    existing = connection.execute(
        "SELECT id FROM cost_records WHERE event_id = ? AND suit_id IS NULL AND cost_scope = 'event_total'", (event_id,)
    ).fetchone()
    if diamond_cost:
        if existing:
            connection.execute("UPDATE cost_records SET cost_text = ? WHERE id = ?", (diamond_cost, existing[0]))
        else:
            connection.execute(
                "INSERT INTO cost_records (event_id, suit_id, cost_scope, cost_text) VALUES (?, NULL, 'event_total', ?)",
                (event_id, diamond_cost),
            )
    elif existing:
        connection.execute("DELETE FROM cost_records WHERE id = ?", (existing[0],))


def _migrate_suit_images_to_shared_urls(connection: sqlite3.Connection) -> None:
    """Allow suit images to reference raw media or one administrator-entered URL."""
    columns = {
        str(row[1]): bool(row[3])
        for row in connection.execute("PRAGMA table_info(suit_images)").fetchall()
    }
    if "image_url" in columns and not columns.get("raw_post_image_id", False):
        return
    rows = connection.execute(
        "SELECT id, suit_id, raw_post_image_id, display_order, is_primary FROM suit_images ORDER BY id"
    ).fetchall()
    foreign_keys_enabled = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    if foreign_keys_enabled:
        connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN")
        connection.executescript(
            """
            CREATE TABLE suit_images_rebuilt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                suit_id INTEGER NOT NULL,
                raw_post_image_id INTEGER,
                image_url TEXT,
                display_order INTEGER NOT NULL DEFAULT 0,
                is_primary INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (suit_id) REFERENCES suits(id) ON DELETE CASCADE,
                FOREIGN KEY (raw_post_image_id) REFERENCES raw_post_images(id) ON DELETE CASCADE,
                CHECK (raw_post_image_id IS NOT NULL OR image_url IS NOT NULL),
                UNIQUE(suit_id, raw_post_image_id)
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO suit_images_rebuilt (
                id, suit_id, raw_post_image_id, image_url, display_order, is_primary
            ) VALUES (?, ?, ?, NULL, ?, ?)
            """,
            rows,
        )
        connection.execute("DROP TABLE suit_images")
        connection.execute("ALTER TABLE suit_images_rebuilt RENAME TO suit_images")
        connection.execute(
            "CREATE UNIQUE INDEX idx_suit_images_one_primary "
            "ON suit_images(suit_id) WHERE is_primary = 1"
        )
        connection.execute("CREATE INDEX idx_suit_images_suit_id ON suit_images(suit_id)")
        connection.execute(
            "CREATE UNIQUE INDEX idx_suit_images_manual_url "
            "ON suit_images(suit_id, image_url) WHERE image_url IS NOT NULL"
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if foreign_keys_enabled:
            connection.execute("PRAGMA foreign_keys = ON")


def _migrate_series_contents_to_suit_links(connection: sqlite3.Connection) -> None:
    """Replace legacy Series content name snapshots with canonical suit links."""
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(series_contents)").fetchall()}
    if "suit_id" in columns and "name" not in columns:
        return
    rows = connection.execute(
        "SELECT id, series_id, name, type, display_order, notes, created_at, updated_at "
        "FROM series_contents ORDER BY id"
    ).fetchall()
    foreign_keys_enabled = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    if foreign_keys_enabled:
        connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN")
        connection.executescript(
            """
            CREATE TABLE series_contents_rebuilt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_id INTEGER NOT NULL,
                suit_id INTEGER NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('main', 'live2d', 'minor', 'frame', 'other')),
                display_order INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE,
                FOREIGN KEY (suit_id) REFERENCES suits(id) ON DELETE CASCADE,
                UNIQUE(series_id, suit_id)
            );
            """
        )
        for row_id, series_id, name, content_type, display_order, notes, created_at, updated_at in rows:
            connection.execute(
                """
                INSERT INTO suits (name, is_live2d, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO NOTHING
                """,
                (name, int(str(content_type) == "live2d"), created_at, updated_at),
            )
            suit_id = connection.execute("SELECT id FROM suits WHERE name = ?", (name,)).fetchone()[0]
            if str(content_type) == "live2d":
                connection.execute("UPDATE suits SET is_live2d = 1 WHERE id = ?", (suit_id,))
            connection.execute(
                """
                INSERT OR IGNORE INTO series_contents_rebuilt (
                    id, series_id, suit_id, type, display_order, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, series_id, suit_id, content_type, display_order, notes, created_at, updated_at),
            )
        connection.execute("DROP TABLE series_contents")
        connection.execute("ALTER TABLE series_contents_rebuilt RENAME TO series_contents")
        connection.execute(
            "CREATE INDEX idx_series_contents_order ON series_contents(series_id, display_order, id)"
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if foreign_keys_enabled:
            connection.execute("PRAGMA foreign_keys = ON")


def _column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    """Return whether an existing SQLite table already has a column."""
    return any(
        row[1] == column_name
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    )


def _initialize_knowledge_provenance_columns(connection: sqlite3.Connection) -> None:
    """Add compatible provenance fields to existing knowledge-base databases.

    SQLite cannot add these columns inside the original CREATE TABLE statements for
    installations that already have the tables, so this is an additive migration.
    No table is rebuilt or removed.
    """
    fields = {
        "events": (
            ("content_type", "TEXT NOT NULL DEFAULT 'event'"),
            ("event_status", "TEXT"),
            ("is_visible", "INTEGER NOT NULL DEFAULT 1"),
            ("data_status", "TEXT NOT NULL DEFAULT 'auto'"),
            ("source_raw_post_id", "INTEGER"),
            ("source_section_hash", "TEXT"),
            ("source_splitter_version", "TEXT"),
            ("created_via", "TEXT NOT NULL DEFAULT 'auto'"),
            ("updated_via", "TEXT NOT NULL DEFAULT 'auto'"),
        ),
        "series": (
            ("event_id", "INTEGER"),
        ),
        "event_periods": (
            ("data_status", "TEXT NOT NULL DEFAULT 'auto'"),
            ("source_raw_post_id", "INTEGER"),
            ("updated_via", "TEXT NOT NULL DEFAULT 'auto'"),
        ),
        "suits": (
            ("data_status", "TEXT NOT NULL DEFAULT 'auto'"),
            ("source_raw_post_id", "INTEGER"),
            ("created_via", "TEXT NOT NULL DEFAULT 'auto'"),
            ("updated_via", "TEXT NOT NULL DEFAULT 'auto'"),
        ),
        "event_suits": (
            ("content_type", "TEXT NOT NULL DEFAULT 'main'"),
            ("appearance_status", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("data_status", "TEXT NOT NULL DEFAULT 'auto'"),
            ("source_raw_post_id", "INTEGER"),
            ("updated_via", "TEXT NOT NULL DEFAULT 'auto'"),
        ),
    }
    for table_name, columns in fields.items():
        for column_name, definition in columns:
            if not _column_exists(connection, table_name, column_name):
                connection.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                )
    # Earlier auto-import revisions used ``parser`` as the creator label.  Keep
    # those unedited records eligible for the safe auto-suit cleanup tool.
    connection.execute(
        "UPDATE suits SET created_via = 'auto' WHERE created_via = 'parser' AND data_status = 'auto'"
    )


def _migrate_events_name_unique_constraint(connection: sqlite3.Connection) -> None:
    """Remove the legacy unique event-name constraint without losing knowledge data."""
    unique_name_index = _find_unique_name_index(connection, "events")
    if unique_name_index is None:
        return

    def snapshot(table_name: str) -> tuple[list[str], list[tuple[object, ...]]]:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
        ).fetchone()
        if exists is None:
            return [], []
        columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table_name})")]
        return columns, connection.execute(f"SELECT * FROM {table_name}").fetchall()

    dependent_rows = {
        table_name: snapshot(table_name)
        for table_name in ("event_periods", "event_suits", "cost_records")
    }
    has_series = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'series'"
    ).fetchone()
    series_links = (
        connection.execute("SELECT id, event_id FROM series WHERE event_id IS NOT NULL").fetchall()
        if has_series is not None
        else []
    )

    foreign_keys_enabled = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    if foreign_keys_enabled:
        connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(
            """
            BEGIN;
            CREATE TABLE events_rebuilt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                official_series TEXT,
                event_type_id INTEGER,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'event',
                event_status TEXT,
                is_visible INTEGER NOT NULL DEFAULT 1,
                data_status TEXT NOT NULL DEFAULT 'auto',
                source_raw_post_id INTEGER,
                source_section_hash TEXT,
                source_splitter_version TEXT,
                created_via TEXT NOT NULL DEFAULT 'auto',
                updated_via TEXT NOT NULL DEFAULT 'auto',
                FOREIGN KEY (event_type_id) REFERENCES event_types(id)
            );

            INSERT INTO events_rebuilt (
                id, name, official_series, event_type_id, description, created_at,
                updated_at, content_type, event_status, is_visible, data_status,
                source_raw_post_id, source_section_hash, source_splitter_version,
                created_via, updated_via
            )
            SELECT
                id, name, official_series, event_type_id, description, created_at,
                updated_at, content_type, event_status, is_visible, data_status,
                source_raw_post_id, source_section_hash, source_splitter_version,
                created_via, updated_via
            FROM events;

            DROP TABLE events;
            ALTER TABLE events_rebuilt RENAME TO events;
            """
        )
        for table_name, (columns, rows) in dependent_rows.items():
            if not columns or not rows:
                continue
            placeholders = ", ".join("?" for _ in columns)
            connection.executemany(
                f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
                rows,
            )
        if series_links:
            connection.executemany("UPDATE series SET event_id = ? WHERE id = ?", ((event_id, series_id) for series_id, event_id in series_links))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if foreign_keys_enabled:
            connection.execute("PRAGMA foreign_keys = ON")


def _find_unique_name_index(
    connection: sqlite3.Connection, table_name: str
) -> str | None:
    """Return a single-column UNIQUE index for ``name``, if the table has one."""
    for row in connection.execute(f"PRAGMA index_list({table_name})"):
        index_name, is_unique = str(row[1]), bool(row[2])
        if not is_unique:
            continue
        escaped_index_name = index_name.replace('"', '""')
        columns = [
            str(column[2])
            for column in connection.execute(
                f'PRAGMA index_info("{escaped_index_name}")'
            )
        ]
        if columns == ["name"]:
            return index_name
    return None


def initialize_review_tables(connection: sqlite3.Connection) -> None:
    """Create human-review tables between parser drafts and the knowledge base."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS draft_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parse_draft_id INTEGER NOT NULL UNIQUE,
            confirmed_event_name TEXT,
            event_type_id INTEGER,
            acquisition_method_id INTEGER,
            official_series TEXT,
            event_cost_text TEXT,
            live2d_cost_text TEXT,
            review_notes TEXT,
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (parse_draft_id) REFERENCES parse_drafts(id) ON DELETE CASCADE,
            FOREIGN KEY (event_type_id) REFERENCES event_types(id),
            FOREIGN KEY (acquisition_method_id) REFERENCES acquisition_methods(id)
        );

        CREATE TABLE IF NOT EXISTS draft_review_suits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_review_id INTEGER NOT NULL,
            suit_name TEXT NOT NULL,
            display_order INTEGER NOT NULL,
            is_live2d INTEGER NOT NULL DEFAULT 0,
            cost_text TEXT,
            notes TEXT,
            FOREIGN KEY (draft_review_id) REFERENCES draft_reviews(id) ON DELETE CASCADE,
            UNIQUE(draft_review_id, display_order)
        );
        """
    )
    connection.commit()


def announcement_exists(connection: sqlite3.Connection, post_url: str) -> bool:
    """Return whether an existing announcement has the URL."""
    row = connection.execute(
        "SELECT id FROM announcements WHERE post_url = ?", (post_url,)
    ).fetchone()
    return row is not None


def insert_announcement(
    connection: sqlite3.Connection, publish_time: str, content: str, post_url: str
) -> int:
    """Insert an announcement using the legacy schema."""
    cursor = connection.execute(
        "INSERT INTO announcements (publish_time, content, post_url) VALUES (?, ?, ?)",
        (publish_time, content, post_url),
    )
    connection.commit()
    return int(cursor.lastrowid)


def insert_images(
    connection: sqlite3.Connection, announcement_id: int, image_urls: list[str]
) -> None:
    """Insert announcement images using the legacy schema."""
    connection.executemany(
        "INSERT INTO images (announcement_id, image_url) VALUES (?, ?)",
        [(announcement_id, image_url) for image_url in image_urls],
    )
    connection.commit()


def record_announcement(
    connection: sqlite3.Connection,
    publish_time: str,
    content: str,
    post_url: str,
    image_urls: list[str],
) -> int:
    """Persist one fully delivered announcement and all of its images atomically."""
    try:
        connection.execute("BEGIN")
        cursor = connection.execute(
            "INSERT INTO announcements (publish_time, content, post_url) VALUES (?, ?, ?)",
            (publish_time, content, post_url),
        )
        announcement_id = int(cursor.lastrowid)
        connection.executemany(
            "INSERT INTO images (announcement_id, image_url) VALUES (?, ?)",
            [(announcement_id, image_url) for image_url in image_urls],
        )
        connection.commit()
        return announcement_id
    except Exception:
        connection.rollback()
        raise


def init_database(database_path: Path | None = None) -> None:
    """Initialize all application tables once at process startup.

    WAL allows one writer to coexist with readers.  It is configured here rather
    than in every repository connection so routine read paths never issue DDL or
    journal-mode changes while the Discord worker is writing.
    """
    connection = get_connection(database_path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publish_time TEXT NOT NULL,
                content TEXT NOT NULL,
                post_url TEXT UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                announcement_id INTEGER NOT NULL,
                image_url TEXT NOT NULL,
                FOREIGN KEY (announcement_id) REFERENCES announcements(id)
            );
            """
        )
        initialize_raw_tables(connection)
        initialize_announcement_queue_tables(connection)
        connection.commit()
        initialize_parse_draft_tables(connection)
        initialize_knowledge_base_tables(connection)
        initialize_review_tables(connection)
    finally:
        connection.close()
    _INITIALIZED_DATABASES.add((database_path or DATABASE_PATH).resolve())


if __name__ == "__main__":
    init_database()
