"""部署阶段一次性执行：创建 LangGraph checkpoint 表。

用法：python -m app.agents.checkpointer_bootstrap
权限前提：迁移 0004 已创建 langgraph_checkpoints schema 并授予应用角色
USAGE + CREATE（应用角色对 public 无 DDL 权限，这是刻意的最小权限边界）。
"""

from __future__ import annotations

import asyncio

from app.agents.checkpointer import checkpoint_saver
from app.core.logging import configure_logging, get_logger
from app.core.runtime import configure_event_loop_policy

logger = get_logger("bootstrap")


async def main() -> None:
    configure_logging()
    async with checkpoint_saver(setup=True):
        # setup() 本身就是验证：表已存在时是幂等 no-op，权限不足时会直接报错
        pass
    logger.info("checkpointer_bootstrap_ok")


if __name__ == "__main__":
    configure_event_loop_policy()
    asyncio.run(main())
