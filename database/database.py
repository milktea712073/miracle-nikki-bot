import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_crawler import fetch_latest_post

def insert_announcement(conn, publish_time, content, post_url):
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO announcements (publish_time, content, post_url)
    VALUES (?, ?, ?)
    """, (publish_time, content, post_url))

    conn.commit()


conn = sqlite3.connect("database/database.db")

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publish_time TEXT NOT NULL,
    content TEXT NOT NULL,
    post_url TEXT UNIQUE NOT NULL
)
""")

conn.commit()

print("announcements 建立成功")

post = fetch_latest_post()
insert_announcement(
    conn,
    post["publish_time"],
    post["content"],
    post["post_url"],
)

conn.close()