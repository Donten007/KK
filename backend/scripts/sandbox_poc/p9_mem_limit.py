"""P9 内存超限（反向断言）：分配并**触碰** 3GB，基线配 2GB —— 必须被拒。

【需资深】为什么不能只 bytearray(3GB)：初始全零数组会被 Linux 零页优化
吃掉（虚拟地址分配成功但物理页不消耗），MemoryError 永不触发，POC 假阴性。
必须写入非零数据强制触碰物理页。
限额失效不会报错，只会让一个租户打垮共享宿主——它比功能失败更危险。
退出码语义：0 = 限额生效（MemoryError 被捕获）；1 = 限额失效。
"""
import sys

try:
    buf = bytearray(3 * 1024 * 1024 * 1024)
    for i in range(0, len(buf), 4096):  # 每 4KB 页写一个非零字节，强制触碰
        buf[i] = 1
    print("LIMIT_BROKEN")
    sys.exit(1)
except MemoryError:
    print("LIMIT_ENFORCED")
    sys.exit(0)
