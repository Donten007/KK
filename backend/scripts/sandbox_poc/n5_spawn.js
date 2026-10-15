// N5 child_process.spawn：从 Node 内起子进程。
const { spawnSync } = require("child_process");
const r = spawnSync("node", ["-e", "console.log(1)"], { encoding: "utf-8" });
console.log("exitcode =", r.status, "stdout =", r.stdout.trim());
process.exit(r.status === 0 ? 0 : 1);
