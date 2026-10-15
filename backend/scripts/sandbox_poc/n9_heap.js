// N9 内存超限（反向断言）：堆配额 2GB，分配必须失败。
// 退出码语义：0 = 限额生效；1 = 限额失效。
let chunks = [];
try {
  while (true) chunks.push(new Array(1e6).fill(1));
  console.log("LIMIT_BROKEN");
  process.exit(1);
} catch (e) {
  if (String(e.message).includes("heap")) {
    console.log("LIMIT_ENFORCED");
    process.exit(0);
  }
  console.log("LIMIT_BROKEN", e.message);
  process.exit(1);
}
