"""lxml HTML 解析：正文抽取 + 结构化字段（任务 C 的竞品价格/动作抽取基础）。

【实习生可做】调整选择器与抽取规则即可，不需要理解护栏逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from lxml import html as lxml_html

# 这些标签内的文本不是「页面内容」，抽取时丢弃
_STRIP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")
# 价格类文本的常见形态：¥ / ￥ / 元 / USD / $ 后跟数字，或数字 + 元/RMB
_PRICE_HINTS = ("¥", "￥", "元", "rmb", "cny", "$", "usd", "price", "价格")


@dataclass
class PageFacts:
    """从页面抽取的结构化事实。字段缺失时为空列表——**不猜**。"""

    url: str
    title: str | None
    visible_text: str
    text_length: int
    prices: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    parsed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def visible_text(html: str) -> str:
    """抽取可见文本（脚本/样式/模板全部剔除）。"""
    tree = lxml_html.fromstring(html)
    for tag in tree.xpath("//" + " | //".join(_STRIP_TAGS)):
        parent = tag.getparent()
        if parent is not None:
            parent.remove(tag)
    text = tree.text_content()
    return " ".join(text.split())


def parse_page(html: str, url: str) -> PageFacts:
    """解析页面为 PageFacts。解析失败抛 lxml 的错误由调用方映射为 G4 失败。"""
    tree = lxml_html.fromstring(html)

    title = _first_text(tree, "//title")
    text = visible_text(html)
    headings = [
        h.strip()
        for h in tree.xpath("//h1//text() | //h2//text() | //h3//text()")
        if h.strip()
    ][:40]
    links = [
        href
        for href in tree.xpath("//a/@href")
        if isinstance(href, str) and href.startswith("http")
    ][:100]

    return PageFacts(
        url=url,
        title=title.strip() if title else None,
        visible_text=text,
        text_length=len(text),
        prices=extract_prices(text),
        headings=headings,
        links=links,
    )


def extract_prices(text: str, limit: int = 30) -> list[str]:
    """抽取价格片段。**只抽取不推断**——看不懂就返回空，不猜数字。

    竞品监控日报的价格抽取交给 LLM 做结构化，本函数只做「页面上有没有价格」
    的粗筛，供 S2 产出物判定与 LLM 提示使用。
    """
    if not any(hint in text.lower() for hint in _PRICE_HINTS):
        return []
    tokens: list[str] = []
    for raw in text.replace("，", " ").replace("、", " ").split():
        if not raw:
            continue
        has_digit = any(ch.isdigit() for ch in raw)
        has_hint = any(hint in raw.lower() for hint in _PRICE_HINTS)
        if has_digit and has_hint:
            tokens.append(raw)
        if len(tokens) >= limit:
            break
    return tokens


def _first_text(tree: Any, xpath: str) -> str | None:
    nodes = tree.xpath(xpath)
    if not nodes:
        return None
    value = nodes[0]
    return value if isinstance(value, str) else value.text_content()