"""P4 lxml HTML 解析（C 扩展）：L1 抓取的核心依赖，竞品监控日报每步都用它。"""
from lxml import html

doc = html.fromstring("<html><body><h1>Standard Plan</h1></body></html>")
print("title:", doc.xpath("//h1/text()")[0])
