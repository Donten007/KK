"""进程级运行时设置（事件循环策略）。

【需资深】为什么需要：LangGraph checkpointer 依赖 psycopg3 的异步模式，
而 psycopg3 **不支持 Windows 默认的 ProactorEventLoop**
（InterfaceError: cannot use the 'ProactorEventLoop' to run in async mode）。
生产是 Linux（默认 Selector 策略），开发机是 Windows，因此：

- 策略必须在**任何事件循环创建之前**设置，否则已创建的循环改不了
- 因此调用点是进程入口（main / worker / bootstrap），而不是业务模块

重复调用是幂等的（set_event_loop_policy 幂等）。
"""

from __future__ import annotations

import asyncio
import sys

from app.core.logging import get_logger

logger = get_logger("runtime")


def configure_event_loop_policy() -> None:
    if sys.platform != "win32":
        return
    policy = asyncio.get_event_loop_policy()
    if isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy):
        return
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logger.info("event_loop_policy_set", policy="WindowsSelector")