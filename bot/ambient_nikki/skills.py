"""Data-driven Xiao Nuan event copy for Ambient Nikki v1.

The filename remains for compatibility, but these are deliberately not skills:
the Discord output is a brief NPC-like room event with no game mechanics.
"""

from __future__ import annotations

import random
from collections.abc import Callable


PREFIXES: tuple[str, ...] = (
    "小暖偷偷探出頭。",
    "小暖路過聊天室。",
    "小暖冒了出來。",
    "小暖不知道從哪裡跑了過來。",
    "小暖晃進了聊天室。",
    "小暖探頭看了看大家。",
    "小暖抱著一堆布料經過。",
    "小暖踩著輕快的步伐走來。",
    "小暖四處張望了一下。",
    "小暖從衣櫃後面鑽了出來。",
    "小暖抱著大喵路過。",
    "小暖在聊天室門口停了一下。",
)

GENERAL_TARGET_EVENTS: tuple[str, ...] = (
    "偷走了{target}的襪子。",
    "朝{target}扔了一顆鑽石。",
    "把一顆鑽石塞進了{target}的口袋。",
    "替{target}別上了一朵小花。",
    "在{target}的桌上放了一顆糖果。",
    "借走了{target}的一顆鈕扣。",
    "替{target}整理了一下衣領。",
    "把一個蝴蝶結綁在了{target}身上。",
    "塞了一張寫著「加油」的小紙條給{target}。",
    "把一根羽毛放在了{target}頭上。",
    "送了{target}一朵不知道哪裡摘來的花。",
    "往{target}的口袋裡放了亮晶晶的小東西。",
    "幫{target}拍掉了肩膀上的灰塵。",
    "圍著{target}轉了一圈，滿意地點了點頭。",
    "替{target}把一顆鈕扣擦得亮晶晶。",
)

GENERAL_ROOM_EVENTS: tuple[str, ...] = (
    "在聊天室門口放了一束花。",
    "留下了一杯熱奶茶。",
    "抱著一大堆布料跑了過去。",
    "蹲在角落縫起了衣服。",
    "把彩帶撒得到處都是。",
    "在窗邊放了一顆亮晶晶的星星。",
    "留下了一張寫著「今天也要加油」的小紙條。",
    "把地上的鈕扣一顆顆撿了起來。",
    "帶著一隻蝴蝶在聊天室繞了一圈。",
    "坐在角落休息了一會兒。",
    "把一顆糖果藏在了聊天室裡。",
    "抱著大喵晃了一圈。",
    "不知道在衣櫃裡翻找什麼。",
    "哼著歌整理起了衣服。",
    "在地上留下了一小串亮晶晶的腳印。",
    "把一朵小花插在了聊天室門口。",
)

SLEEP_TARGET_EVENTS: tuple[str, ...] = (
    "看見{target}還醒著，默默抱來了一顆枕頭。",
    "替{target}蓋好了棉被。",
    "把一杯溫牛奶放在了{target}手邊。",
    "小聲提醒{target}該睡覺了。",
    "把一顆晚安糖放在了{target}的桌上。",
    "希望{target}今晚能做個好夢。",
)

SLEEP_ROOM_EVENTS: tuple[str, ...] = (
    "幫聊天室關掉了一盞燈。",
    "抱著枕頭打了一個大大的哈欠。",
    "在窗邊看了看高高掛著的月亮。",
    "替大家把棉被角掖好了。",
    "抱著大喵一起打起了瞌睡。",
    "把聊天室的燈光調暗了一點。",
)


def render_general_event(target: str, *, choose: Callable[[tuple[str, ...]], str] = random.choice) -> str:
    return _render(choose(PREFIXES), choose(choose((GENERAL_TARGET_EVENTS, GENERAL_ROOM_EVENTS))), target)


def render_sleep_event(target: str, *, choose: Callable[[tuple[str, ...]], str] = random.choice) -> str:
    return _render(choose(PREFIXES), choose(choose((SLEEP_TARGET_EVENTS, SLEEP_ROOM_EVENTS))), target)


def _render(prefix: str, event: str, target: str) -> str:
    return f"{prefix}\n\n{event.format(target=target)}"
