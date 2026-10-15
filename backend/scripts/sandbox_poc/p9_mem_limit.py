"""P9 内存超限（反向断言）：分配 3GB，基线配 2GB —— 必须被拒。

限额失效不会报错，只会让一个租户打垮共享宿主——它比功能失败更危险。
退出码语义：0 = 限额生效（MemoryError 被捕获）；1 = 限额失效。
"""
import sys

try:
    _ = bytearray(3 * 1024 * 1024 * 1024)
    print("LIMIT_BROKEN")
    sys.exit(1)
except MemoryError:
    print("LIMIT_ENFORCED")
    sys.exit(0)
