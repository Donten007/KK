"""P3 numpy 数组运算（C 扩展 + BLAS）：数据分析类岗位的基础依赖。"""
import numpy as np

a = np.random.rand(100, 100)
print("matmul ok:", (a @ a).shape)
