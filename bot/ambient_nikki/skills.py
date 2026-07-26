"""Data-driven Xiao Nuan event copy for Ambient Nikki v1.

The filename remains for compatibility, but these are deliberately not skills:
the Discord output is a brief NPC-like room event with no game mechanics.
"""

from __future__ import annotations

import random
from collections.abc import Callable


PREFIXES: tuple[str, ...] = (
    "小暖偷偷探出頭 🌸",
    "小暖路過聊天室 ✨",
    "小暖不知道從哪裡冒了出來 ⭐",
    "小暖抱著一堆布料經過 🧵",
    "小暖踩著輕快的步伐走來 🎶",
    "小暖晃進了聊天室 💎",
    "小暖探頭看了看大家 🌼",
    "小暖抱著大喵路過 🐱",
    "小暖四處張望了一下 🌷",
    "小暖今天心情很好 🎵",
    "小暖在聊天室門口停了一下 ✨",
    "小暖躡手躡腳地靠近 🌸",
    "小暖從衣櫃後面鑽了出來 🎀",
    "小暖抱著一束花走了過來 🌼",
    "小暖開心地哼著歌 🎶",
    "小暖帶著蝴蝶繞了過來 🦋",
    "小暖整理著裙擺走來 💎",
    "小暖抱著幾顆鈕扣跑來 🎀",
    "小暖在窗邊探了探頭 ⭐",
    "小暖踩著花瓣走進來 🌷",
)

GENERAL_TARGET_EVENTS: tuple[str, ...] = (
    "偷走了{target}的襪子",
    "朝{target}扔了一顆鑽石",
    "把一顆鑽石塞進了{target}的口袋",
    "替{target}別上了一朵小花",
    "在{target}的桌上放了一顆糖果",
    "借走了{target}的一顆鈕扣",
    "替{target}整理了一下衣領",
    "把一個蝴蝶結綁在了{target}身上",
    "把一張寫著加油的小紙條放在{target}身邊",
    "把一根羽毛放在了{target}頭上",
    "送了{target}一朵不知道哪裡摘來的花",
    "往{target}的口袋裡放了亮晶晶的小東西",
    "幫{target}拍掉肩膀上的灰塵",
    "圍著{target}轉了一圈後滿意地點了點頭",
    "替{target}把一顆鈕扣擦得亮晶晶",
    "替{target}繫上了一條柔軟的緞帶",
    "把一小片花瓣放在{target}手心",
    "送了{target}一張新畫好的搭配草圖",
    "把一枚小徽章別在{target}衣角",
    "替{target}把髮絲整理好",
    "讓一隻蝴蝶停在{target}肩上",
    "往{target}的口袋裡放了一顆鑽石",
    "把一小袋金幣塞給了{target}",
    "往{target}手上放了幾枚金幣",
    "替{target}撿到了一枚星光幣",
    "把幾枚星光幣放在{target}身旁",
    "把一枚金幣放進了{target}掌心",
    "替{target}把一顆鑽石擦得亮晶晶",
    "在{target}的書頁裡夾了一枚星光幣",
    "把一枚星光幣別在{target}的衣角",
    "讓{target}在椅子下發現了一小袋金幣",
    "送了{target}一朵綁著緞帶的小花",
    "把一片羽毛放在{target}的手邊",
    "替{target}撿起掉在地上的蝴蝶結",
    "把一顆小星星掛在{target}的桌角",
    "在{target}的口袋裡藏了一顆糖果",
    "替{target}挑了一朵剛盛開的小花",
    "送了{target}一個小熊玩偶",
    "把一小卷布料交到{target}手上",
    "替{target}在衣領上別了一根羽毛",
    "把一張寫著今天也要加油的小紙條塞給了{target}",
    "替{target}繫好了一條飄起來的緞帶",
    "把一隻小蝴蝶引到{target}身邊",
    "往{target}的桌上放了一份小小的茶點",
    "把一個軟綿綿的抱枕靠在{target}身旁",
)

GENERAL_ROOM_EVENTS: tuple[str, ...] = (
    "在聊天室門口放了一束花",
    "留下了一杯熱奶茶",
    "抱著一大堆布料跑了過去",
    "把彩帶撒得到處都是",
    "留下了一小串亮晶晶的腳印",
    "帶著一隻蝴蝶繞了一圈",
    "在角落縫起了衣服",
    "把一顆糖果藏在聊天室裡",
    "抱著大喵晃了一圈",
    "把一朵花放在窗邊",
    "在聊天室留下一張小紙條",
    "把一顆亮晶晶的小星星掛在角落",
    "留下了一點閃閃發亮的粉末",
    "蹲在角落挑選起了布料",
    "把地上的鈕扣一顆顆撿了起來",
    "坐在窗邊整理起了緞帶",
    "在衣櫃裡翻找著不知道什麼東西",
    "哼著歌把花瓣排成了一圈",
    "替門口的盆栽澆了一點水",
    "在桌上擺好了一小排糖果",
    "把一卷漂亮的布料放在角落",
    "留下了一顆鑽石後就跑掉了",
    "把幾枚金幣藏進聊天室角落",
    "在地上撒了幾枚星光幣",
    "不知道把一袋金幣放到哪裡去了",
    "把一枚星光幣放在窗台上",
    "在花盆旁留下一顆鑽石",
    "把幾枚金幣排成了一個小圓圈",
    "把一顆鑽石藏在布料下面",
    "把一袋星光幣放在大喵旁邊",
    "在角落發現了一枚閃亮的金幣",
    "把幾片花瓣灑得到處都是",
    "留下了一束剛綁好的小花",
    "把一盒鈕扣整齊地放在桌上",
    "把幾條緞帶掛在聊天室門口",
    "在窗邊留下一根輕飄飄的羽毛",
    "替聊天室掛上了一顆小星星",
    "把一張寫著今天也要加油的小紙條放在桌上",
    "留下了一盤小小的茶點",
    "把一個抱枕放在角落的椅子上",
    "讓一隻蝴蝶停在門口的花束上",
    "替大喵留了一顆糖果",
    "把一隻小熊玩偶放在窗邊",
    "把針線盒收進了一個小籃子",
    "在地上留下一點溫柔的星光",
    "把一朵花插在聊天室的花瓶裡",
    "把幾顆鈕扣排成了一條小路",
    "留下一小卷繡著花紋的布料",
    "把一條蝴蝶結緞帶綁在門把上",
    "把一顆糖果放在茶杯旁邊",
    "替聊天室的抱枕拍得鬆鬆軟軟",
)

SLEEP_TARGET_EVENTS: tuple[str, ...] = (
    "替{target}蓋好了棉被",
    "把一杯溫牛奶放在{target}身邊",
    "提醒{target}該睡覺了",
    "把一顆晚安糖放在{target}的桌上",
    "希望{target}今晚能做個好夢",
    "看見{target}還醒著就默默抱來了一顆枕頭",
    "替{target}把棉被角掖好",
    "把一盞小夜燈放在{target}身邊",
)

SLEEP_ROOM_EVENTS: tuple[str, ...] = (
    "抱著枕頭打了一個哈欠",
    "幫聊天室關掉了一盞燈",
    "把月亮掛得更高了一點",
    "在窗邊看了看高高掛著的月亮",
    "替大家把棉被角掖好了",
    "抱著大喵一起打起了瞌睡",
    "把聊天室的燈光調暗了一點",
    "把窗簾拉好了一點",
)


def render_general_event(target: str, *, choose: Callable[[tuple[str, ...]], str] = random.choice) -> str:
    return _render(choose(PREFIXES), choose(choose((GENERAL_TARGET_EVENTS, GENERAL_ROOM_EVENTS))), target)


def render_sleep_event(target: str, *, choose: Callable[[tuple[str, ...]], str] = random.choice) -> str:
    return _render(choose(PREFIXES), choose(choose((SLEEP_TARGET_EVENTS, SLEEP_ROOM_EVENTS))), target)


def _render(prefix: str, event: str, target: str) -> str:
    return f"{prefix}\n{event.format(target=target)}"
