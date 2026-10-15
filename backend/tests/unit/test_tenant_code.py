"""单元测试：账套号生成（SPEC §12.2 格式断言 ^AC-[0-9A-Z]{8}$）。"""

from __future__ import annotations

import re

from app.utils.ids import generate_tenant_code, is_valid_tenant_code

_PATTERN = re.compile(r"^AC-[0-9A-Z]{8}$")


def test_code_matches_spec_regex() -> None:
    for _ in range(200):
        assert _PATTERN.match(generate_tenant_code())


def test_code_excludes_ambiguous_letters() -> None:
    """Crockford：剔除 I/L/O/U（口述误读高发），SPEC 示例 AC-8F3K2M9W 同为该字母表。"""
    for _ in range(200):
        code = generate_tenant_code()
        body = code[3:]
        assert not set(body) & set("ILOU")


def test_codes_are_unique_in_practice() -> None:
    codes = {generate_tenant_code() for _ in range(2000)}
    # 40 bit 空间下 2000 次采样碰撞概率约 2000^2/2/2^40 ≈ 1.8e-6
    assert len(codes) == 2000


def test_validator() -> None:
    assert is_valid_tenant_code("AC-8F3K2M9W")
    assert not is_valid_tenant_code("AC-8F3K2M9")  # 7 位
    assert not is_valid_tenant_code("AC-8F3K2M9WW")  # 9 位
    assert not is_valid_tenant_code("XX-8F3K2M9W")  # 前缀错
    assert not is_valid_tenant_code("AC-8f3k2m9w")  # 小写
