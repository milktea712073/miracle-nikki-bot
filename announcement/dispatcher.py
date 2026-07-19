"""Discord delivery helpers for v2 announcement state."""

from __future__ import annotations

from typing import Awaitable, Callable

from announcement.state_store import PendingDelivery


async def dispatch_delivery(
    delivery: PendingDelivery,
    resolve_channel: Callable[[int], Awaitable[object]],
    send_payload: Callable[[object, dict[str, object]], Awaitable[list[int | str]]],
) -> list[int | str]:
    """Deliver one channel-specific announcement without mutating state."""
    channel = await resolve_channel(delivery.channel_id)
    return await send_payload(channel, delivery.announcement.payload())
