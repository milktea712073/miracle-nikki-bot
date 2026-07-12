"""Shared player-facing formatting for Miracle Nikki knowledge cards."""

from __future__ import annotations


RESOURCE_DISPLAY = {
    "花鑽": ("💎 花鑽", "鑽"),
    "體力": ("⚡ 體力", "體力"),
    "儲值": ("⭐ 星曜石", "星曜石"),
    "金幣": ("🪙 金幣", "金幣"),
    "免費": ("🎁 免費", None),
    "聯盟": ("🤝 聯盟", None),
    "設計圖": ("📜 設計圖", None),
    "其他": ("🎁 取得方式", None),
}


def format_cost_line(acquisition_method: str | None, cost_text: str | None) -> str | None:
    """Return one compact resource line without duplicating resource units."""
    if not acquisition_method:
        return None
    label, unit = RESOURCE_DISPLAY.get(acquisition_method, ("🎁 取得方式", None))
    if acquisition_method == "免費":
        return label
    if not cost_text or not cost_text.strip():
        return f"{label}：尚未整理"
    cost = cost_text.strip()
    if unit and unit not in cost:
        cost = f"{cost}{unit}"
    return f"{label}：{cost}"


def format_suit_cost_value(acquisition_method: str | None, cost_text: str | None) -> str | None:
    """Format the value portion of a suit-card cost without repeating its method."""
    if acquisition_method == "免費":
        return "免費"
    if not cost_text or not cost_text.strip():
        return acquisition_method or None
    cost = cost_text.strip()
    unit_by_method = {"花鑽": "鑽", "體力": "體力", "儲值": "星曜石", "星曜石": "星曜石"}
    unit = unit_by_method.get(acquisition_method or "")
    if not unit:
        return cost
    compact = cost.replace(" ", "")
    if compact.endswith(unit):
        compact = compact[: -len(unit)].rstrip()
    return f"{compact} {unit}".strip()
