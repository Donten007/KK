"""业务异常与错误码（SPEC §5.4）。

跨租户铁律：1003 只允许出现在「租户内权限不足」场景；跨租户一律 1004/404——
403 会泄露资源存在性，形成可批量扫描的 oracle（SPEC §4.4 / 坑 5）。
"""

from __future__ import annotations

from typing import Any, ClassVar


class ErrorCode:
    """错误码常量 + HTTP 状态映射。"""

    VALIDATION_FAILED = 1001
    UNAUTHENTICATED = 1002
    FORBIDDEN = 1003
    NOT_FOUND = 1004
    CONFLICT = 1005
    PAYLOAD_TOO_LARGE = 1006
    RATE_LIMITED = 1007
    BUDGET_EXHAUSTED = 2002
    CAPABILITY_INSUFFICIENT = 3001
    PROVIDER_UNAVAILABLE = 3002
    INVALID_CREDENTIAL = 3003
    TARGET_REQUIRES_JS_RENDER = 4001
    ROBOTS_DISALLOWED = 4002
    INTERNAL_ERROR = 5001

    # (code, http_status, 默认消息)。消息给终端用户，禁止暴露系统内部行为。
    _TABLE: ClassVar[tuple[tuple[int, int, str], ...]] = (
        (1001, 400, "参数校验失败"),
        (1002, 401, "未认证或登录已过期"),
        (1003, 403, "权限不足"),
        (1004, 404, "资源不存在"),
        (1005, 409, "资源冲突"),
        (1006, 413, "上传内容超出大小上限"),
        (1007, 429, "请求过于频繁，请稍后再试"),
        (2002, 402, "本月预算已用尽"),
        (3001, 409, "模型能力不满足当前任务"),
        (3002, 502, "模型服务暂时不可用"),
        (3003, 400, "模型密钥无效"),
        (4001, 422, "目标页面需要浏览器渲染，当前抓取层不支持"),
        (4002, 422, "目标站点禁止抓取"),
        (5001, 500, "服务内部错误"),
    )

    _http: ClassVar[dict[int, int]] = {c: h for c, h, _ in _TABLE}
    _default_msg: ClassVar[dict[int, str]] = {c: m for c, _, m in _TABLE}

    @classmethod
    def http_status(cls, code: int) -> int:
        return cls._http.get(code, 500)

    @classmethod
    def default_message(cls, code: int) -> str:
        return cls._default_msg.get(code, "服务内部错误")


class BusinessError(Exception):
    """业务异常基类。service 层抛出，全局处理器转信封响应。

    使用约束：message 是给终端用户看的，禁止出现堆栈、SQL、内部阈值。
    """

    def __init__(self, code: int, message: str | None = None, *, data: Any = None) -> None:
        self.code = code
        self.message = message or ErrorCode.default_message(code)
        self.data = data
        super().__init__(self.message)


class ValidationError(BusinessError):
    def __init__(self, message: str = "参数校验失败") -> None:
        super().__init__(ErrorCode.VALIDATION_FAILED, message)


class UnauthenticatedError(BusinessError):
    def __init__(self, message: str = "未认证或登录已过期") -> None:
        super().__init__(ErrorCode.UNAUTHENTICATED, message)


class ForbiddenError(BusinessError):
    """租户内权限不足。禁止用于跨租户场景（跨租户一律 NotFoundError）。"""

    def __init__(self, message: str = "权限不足") -> None:
        super().__init__(ErrorCode.FORBIDDEN, message)


class NotFoundError(BusinessError):
    """资源不存在或跨租户（不区分，SPEC §4.4 越权响应语义）。"""

    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(ErrorCode.NOT_FOUND, message)


class ConflictError(BusinessError):
    def __init__(self, message: str = "资源冲突") -> None:
        super().__init__(ErrorCode.CONFLICT, message)


class PayloadTooLargeError(BusinessError):
    def __init__(self, message: str = "上传内容超出大小上限") -> None:
        super().__init__(ErrorCode.PAYLOAD_TOO_LARGE, message)


class RateLimitedError(BusinessError):
    def __init__(self, message: str = "请求过于频繁，请稍后再试") -> None:
        super().__init__(ErrorCode.RATE_LIMITED, message)


class BudgetExhaustedError(BusinessError):
    """月度预算用尽（纯 BYOK 语义：帮客户盯自己的钱，ADR-019）。"""

    def __init__(self, message: str = "本月预算已用尽") -> None:
        super().__init__(ErrorCode.BUDGET_EXHAUSTED, message)


class CapabilityInsufficientError(BusinessError):
    """模型能力不满足（fail-closed，ADR-013）。data 带缺失能力列表。"""

    def __init__(self, missing: list[str], message: str = "模型能力不满足当前任务") -> None:
        super().__init__(ErrorCode.CAPABILITY_INSUFFICIENT, message, data={"missing": missing})


class ProviderUnavailableError(BusinessError):
    def __init__(self, message: str = "模型服务暂时不可用") -> None:
        super().__init__(ErrorCode.PROVIDER_UNAVAILABLE, message)


class InvalidCredentialError(BusinessError):
    def __init__(self, message: str = "模型密钥无效") -> None:
        super().__init__(ErrorCode.INVALID_CREDENTIAL, message)


class RobotsDisallowedError(BusinessError):
    """G1：目标站点 robots.txt 禁止抓取（AC-B3）。"""

    def __init__(self, domain: str, message: str = "目标站点禁止抓取") -> None:
        super().__init__(ErrorCode.ROBOTS_DISALLOWED, message, data={"domain": domain})


class TargetRequiresJsRenderError(BusinessError):
    """AC-B7：JS 重渲染站点必须显式失败，禁止静默返回空内容。"""

    def __init__(self, url: str, message: str = "目标页面需要浏览器渲染，当前抓取层不支持") -> None:
        super().__init__(ErrorCode.TARGET_REQUIRES_JS_RENDER, message, data={"url": url})
