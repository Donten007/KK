"""P10 文件描述符超限（反向断言）：ulimit nofile=1024 是否生效。

退出码语义：0 = 限额生效；1 = 限额失效。
"""
import sys

handles = []
try:
    for _ in range(2000):
        # 故意不用 context manager：本测试就是要持有 fd 直到超限（反向断言）
        handles.append(open("/dev/null", "w"))  # noqa: SIM115
    print("LIMIT_BROKEN")
    sys.exit(1)
except OSError:
    print("LIMIT_ENFORCED")
    sys.exit(0)
finally:
    for h in handles:
        h.close()
