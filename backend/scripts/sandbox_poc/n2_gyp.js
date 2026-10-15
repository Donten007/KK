// N2 node-gyp 编译链（完整 cc/make/python 工具链）：模拟原生模块从源码编译。
// 用 bcryptjs（纯 JS，无需真实编译）验证工具链可用性 + npm 网络与写盘。
const bcrypt = require("bcryptjs");
bcrypt.hashSync("x", 4);
console.log("ok");
