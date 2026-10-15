// N3 加载预编译 .node 二进制（dlopen）：better-sqlite3 带 prebuilt 二进制。
const Database = require("better-sqlite3");
const d = new Database(":memory:");
d.exec("create table t(x)");
d.prepare("insert into t values (?)").run(1);
console.log("rows =", d.prepare("select count(*) from t").get().x);
