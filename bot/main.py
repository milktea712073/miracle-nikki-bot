"""Discord entry point for the Miracle Nikki latest-post command."""

import asyncio
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_crawler import fetch_latest_post


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

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.command(name="latest")
async def latest(ctx: commands.Context[commands.Bot]) -> None:
    """Reply with the latest official Facebook post."""
    post = await asyncio.to_thread(fetch_latest_post)
    embed = discord.Embed(
        title="\U0001f338 \u5947\u8e5f\u6696\u6696\u6700\u65b0\u516c\u544a",
        description=(
            f"\U0001f4c5 \u767c\u5e03\u6642\u9593\n{post['time']}\n\n"
            f"\U0001f4dd \u516c\u544a\u5167\u5bb9\n{post['content']}"
        ),
        color=discord.Color.from_rgb(255, 183, 197),
    )
    if post["image_url"]:
        embed.set_image(url=post["image_url"])

    await ctx.send(embed=embed)


def main() -> None:
    """Start the Discord bot with the token from .env."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing from .env.")
    bot.run(token)


if __name__ == "__main__":
    main()
