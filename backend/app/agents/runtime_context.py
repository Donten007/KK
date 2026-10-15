"""图执行的运行时上下文（contextvars）。

为什么需要：LangGraph 节点函数是闭包，拿不到 request 级依赖（DB 会话、租户上下文、
取消信号）。用 contextvars 把「本次运行的上下文」注入节点执行期，
避免把 DB 会话塞进 checkpoint（**checkpoint 只存可序列化图状态**，坑 3）。

【需资深】contextvars 与 asyncio 的关系：每个 asyncio Task 复制一份上下文，
因此并发运行多个 goal 不会互相污染。禁止用模块级全局变量代替。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

    from app.agents.graph import GraphContext

_current_cancel_event: ContextVar[asyncio.Event | None] = ContextVar(
    "opc_current_cancel_event", default=None
)
_current_graph_context: ContextVar[GraphContext | None] = ContextVar(
    "opc_current_graph_context", default=None
)


def set_cancel_event(event: asyncio.Event | None) -> Token[Any]:
    return _current_cancel_event.set(event)


def current_cancel_event() -> asyncio.Event | None:
    return _current_cancel_event.get()


def set_graph_context(ctx: GraphContext) -> Token[Any]:
    return _current_graph_context.set(ctx)


def reset_graph_context(token: Token[Any]) -> None:
    _current_graph_context.reset(token)


def current_graph_context() -> GraphContext | None:
    return _current_graph_context.get()