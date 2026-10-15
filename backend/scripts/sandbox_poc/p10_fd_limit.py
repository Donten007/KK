"""P10 文件描述符超限（反向断言）：ulimit nofile=1024 是否生效。

退出码语义：0 = 限额生效；1 = 限额失效。
"""
import sys

handles = []
try:
    for i in range(2000):
        handles.append(open("/dev/null", "w"))
    print("LIMIT_BROKEN")
    sys.exit(1)
except OSError:
    print("LIMIT_ENFORCED")
    sys.exit(0)
finally:
    for h in handles:
        h.close()
