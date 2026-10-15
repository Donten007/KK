// N7 worker_threads：gVisor 的线程模型与内核不同，这是独立 syscall 路径，
// 编译和进程场景都测不到它。
const { Worker } = require("worker_threads");
new Worker("console.log('worker ok')", { eval: true }).on("exit", (code) =>
  process.exit(code),
);
