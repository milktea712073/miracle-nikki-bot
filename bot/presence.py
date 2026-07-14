import itertools

import discord
from discord.ext import tasks


PRESENCE_MESSAGES = [
    "試穿新衣服～",
    "幫暖媽花鑽石",
    "整理衣櫃中",
    "搭配今日穿搭",
    "等待免費套裝",
    "努力存鑽石",
    "整理套裝圖鑑",
    "尋找新的活動",
]


class PresenceRotation:
    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot
        self._messages = itertools.cycle(PRESENCE_MESSAGES)

    @tasks.loop(minutes=10)
    async def rotate(self) -> None:
        message = next(self._messages)

        await self.bot.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name=message),
        )

    @rotate.before_loop
    async def before_rotate(self) -> None:
        await self.bot.wait_until_ready()

    def start(self) -> None:
        if not self.rotate.is_running():
            self.rotate.start()

    def stop(self) -> None:
        if self.rotate.is_running():
            self.rotate.cancel()


_presence_rotation: PresenceRotation | None = None


def start_presence_rotation(bot: discord.Client) -> PresenceRotation:
    global _presence_rotation

    if _presence_rotation is None:
        _presence_rotation = PresenceRotation(bot)

    _presence_rotation.start()
    return _presence_rotation