// N6 net 模块出网：HTTPS 请求，验证 socket 路径。
require("https")
  .get("https://example.com", (res) => {
    console.log("status =", res.statusCode);
    process.exit(res.statusCode && res.statusCode < 500 ? 0 : 1);
  })
  .on("error", (e) => {
    console.error("ERR", e.message);
    process.exit(1);
  });
