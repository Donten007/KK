"""协作式取消与 5 秒兜底收敛（ADR-017 / 坑 10）。

实现顺序**不可颠倒**：
  1. API 收到 cancel → 立即置 status=stopping → 返回 200（不等任务真停）
  2. 向 worker 发协作式取消信号（asyncio.Event）
  3. worker 在步骤边界检查取消标志 → 保存 checkpoint → 置 cancelled
  4. 若 5s 内未完成 → 巡检器强制收敛为 cancelled（UI 永不卡中间态）

cancel 幂等：重复调用返回同一状态不报错，且只发一次取消信号
（registry 里 Event 已置位则不再重复通知）。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger("cancel")

# ADR-017：stopping 最长 5 秒，超时由巡检器强制收敛
STOPPING_TIMEOUT_SECONDS = 5.0


@dataclass
class CancelHandle:
    """单个运行任务的取消句柄。"""

    goal_id: uuid.UUID
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[Any] | None = None

    def request_cancel(self) -> bool:
        """返回 True 表示这是首次发起取消（重复调用返回 False，不重复发信号）。"""
        if self.cancel_event.is_set():
            return False
        self.cancel_event.set()
        return True


class CancelRegistry:
    """进程内运行任务登记表。

    【需资深】多 worker 部署下本表只在单进程内有效——跨进程取消依赖
    Hatchet/Redis 信号（Phase 3）。当前实现保证「同一进程内 cancel 幂等 + 先置
    stopping」，跨进程兜底由 5 秒巡检器强制收敛（DB 状态是唯一权威）。
    """

    def __init__(self) -> None:
        self._handles: dict[uuid.UUID, CancelHandle] = {}
        self._lock = asyncio.Lock()

    async def register(self, goal_id: uuid.UUID) -> CancelHandle:
        async with self._lock:
            handle = self._handles.get(goal_id)
            if handle is None:
                handle = CancelHandle(goal_id=goal_id)
                self._handles[goal_id] = handle
            return handle

    async def unregister(self, goal_id: uuid.UUID) -> None:
        async with self._lock:
            self._handles.pop(goal_id, None)

    async def get(self, goal_id: uuid.UUID) -> CancelHandle | None:
        async with self._lock:
            return self._handles.get(goal_id)

    async def request_cancel(self, goal_id: uuid.UUID) -> bool:
        handle = await self.get(goal_id)
        if handle is None:
            # 未在运行（可能是 queued 或已完成）：由服务层按状态机处理
            return False
        first = handle.request_cancel()
        if first:
            logger.info("cancel_signal_sent", goal_id=str(goal_id))
        return first


# 进程级单例
registry = CancelRegistry()