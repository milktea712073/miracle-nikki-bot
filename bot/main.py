"""Discord entry point for the Miracle Nikki latest-post command."""

import asyncio
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands, tasks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_crawler import fetch_latest_post
from database.database import (
    get_connection,
    announcement_exists,
    insert_announcement,
)


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries from a local .env file."""
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_dotenv(PROJECT_ROOT / ".env")
CHANNEL_IDS = [
    int(channel_id.strip())
    for channel_id in os.getenv("CHANNEL_IDS", "").split(",")
    if channel_id.strip()
]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user} 已上線！")

    if not check_new_post.is_running():
        check_new_post.start()


@tasks.loop(minutes=5)
async def check_new_post():
    print("開始檢查 Facebook...")

    post = await asyncio.to_thread(fetch_latest_post)

    conn = get_connection()

    if announcement_exists(conn, post["post_url"]):
        print("沒有新公告")
        conn.close()
        return

    insert_announcement(
        conn,
        post["publish_time"],
        post["content"],
        post["post_url"],
    )
    print("🎉 發現新公告")

    conn.close()

    embed = discord.Embed(
        title="🌸 奇蹟暖暖最新公告",
        description=(
            f"📅 發布日期\n{post['publish_time']}\n\n"
            f"📝 公告內容\n{post['content']}"
        ),
        color=discord.Color.from_rgb(255, 183, 197),
    )

    if post["image_urls"]:
        embed.set_image(url=post["image_urls"][0])
    
    for channel_id in CHANNEL_IDS:
        channel = bot.get_channel(channel_id)

        if channel is None:
            continue

        await channel.send(embed=embed)

        for image in post["image_urls"][1:]:
            await channel.send(image)

@bot.command(name="latest")
async def latest(ctx: commands.Context[commands.Bot]) -> None:
    """Reply with the latest official Facebook post."""
    post = await asyncio.to_thread(fetch_latest_post)
    embed = discord.Embed(
        title="\U0001f338 \u5947\u8e5f\u6696\u6696\u6700\u65b0\u516c\u544a",
        description=(
            f"\U0001f4c5 \u767c\u5e03\u65e5\u671f\n{post['publish_time']}\n\n"
            f"\U0001f4dd \u516c\u544a\u5167\u5bb9\n{post['content']}"
        ),
        color=discord.Color.from_rgb(255, 183, 197),
    )
    if post["image_urls"]:
        embed.set_image(url=post["image_urls"][0])

    await ctx.send(embed=embed)

    for image in post["image_urls"][1:]:
        await ctx.send(image)


def main() -> None:
    """Start the Discord bot with the token from .env."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing from .env.")
    bot.run(token)


if __name__ == "__main__":
    main()
