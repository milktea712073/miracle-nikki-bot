import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_crawler import fetch_latest_post

def announcement_exists(conn, post_url):
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id
    FROM announcements
    WHERE post_url = ?
    """, (post_url,))

    return cursor.fetchone() is not None

def insert_announcement(conn, publish_time, content, post_url):
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO announcements (publish_time, content, post_url)
    VALUES (?, ?, ?)
    """, (publish_time, content, post_url))

    conn.commit()
    return cursor.lastrowid

def insert_images(conn, announcement_id, image_urls):
    cursor = conn.cursor()

    for image_url in image_urls:
        cursor.execute("""
        INSERT INTO images (announcement_id, image_url)
        VALUES (?, ?)
        """, (announcement_id, image_url))

    conn.commit()

def get_connection():
    return sqlite3.connect("database/database.db")

def init_database():
    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        publish_time TEXT NOT NULL,
        content TEXT NOT NULL,
        post_url TEXT UNIQUE NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        announcement_id INTEGER NOT NULL,
        image_url TEXT NOT NULL,
        FOREIGN KEY (announcement_id) REFERENCES announcements(id)
    )
    """)

    conn.commit()

    print("資料庫初始化完成")
    conn.close()

if __name__ == "__main__":
    init_database()