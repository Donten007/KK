"""P2 pysqlite3 本地 DB 读写（C 扩展）：客户 Excel 导入后的结构化存储走它。"""
import sqlite3

c = sqlite3.connect(":memory:")
c.execute("create table t(x)")
c.executemany("insert into t values (?)", [(i,) for i in range(100)])
c.commit()
print("rows =", c.execute("select count(*) from t").fetchone()[0])
