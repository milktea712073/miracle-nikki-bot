"""SQLite connection and schema helpers."""

import sqlite3
import threading
from pathlib import Path


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
    """Create raw Facebook post tables without modifying existing tables."""
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

        CREATE INDEX IF NOT EXISTS idx_raw_posts_url ON raw_posts(url);
        CREATE INDEX IF NOT EXISTS idx_raw_posts_published_at ON raw_posts(published_at);
        CREATE INDEX IF NOT EXISTS idx_raw_posts_parse_status ON raw_posts(parse_status);
        """
    )
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
            raw_post_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'sending', 'sent', 'skipped', 'failed')),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            sent_at TEXT,
            FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE,
            UNIQUE(raw_post_id)
        );

        CREATE INDEX IF NOT EXISTS idx_announcement_jobs_status_created
            ON announcement_jobs(status, created_at);
        """
    )
    connection.commit()


def initialize_parse_draft_tables(connection: sqlite3.Connection) -> None:
    """Create parser draft tables without touching the knowledge-base schema."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS parse_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_post_id INTEGER NOT NULL,
            parser_version TEXT NOT NULL,
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
            UNIQUE(raw_post_id, parser_version)
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
    connection.commit()


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
            name TEXT NOT NULL UNIQUE,
            official_series TEXT,
            event_type_id INTEGER,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
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
            raw_post_image_id INTEGER NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            is_primary INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (suit_id) REFERENCES suits(id) ON DELETE CASCADE,
            FOREIGN KEY (raw_post_image_id) REFERENCES raw_post_images(id) ON DELETE CASCADE,
            UNIQUE(suit_id, raw_post_image_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_suit_images_one_primary
            ON suit_images(suit_id) WHERE is_primary = 1;
        CREATE INDEX IF NOT EXISTS idx_suit_images_suit_id
            ON suit_images(suit_id);
        """
    )
    _initialize_knowledge_provenance_columns(connection)
    connection.commit()


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
            ("created_via", "TEXT NOT NULL DEFAULT 'auto'"),
            ("updated_via", "TEXT NOT NULL DEFAULT 'auto'"),
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
