import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { NextConfig } from 'next';

const projectDir = path.dirname(fileURLToPath(import.meta.url));

/**
 * 前端运行时配置。后端地址走 NEXT_PUBLIC_API_BASE_URL，前端不持有任何密钥。
 *
 * [需资深] turbopack.root 提升到仓库根的原因：
 * 设计 Token 唯一来源是 design-system/design-tokens.css（设计师产出，
 * **刻意不复制进前端**，否则会出现两份真相同步问题 —— 那是设计契约事故）。
 * 但 Turbopack 默认以 app 目录为 root，跨 root 导入 CSS 会直接 build 失败
 * （"loader path is outside configured roots"）。
 * 把 root 提到仓库根即可让 token 保持单一来源。
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // 容器化硬要求：`next build` 产出 .next/standalone（自包含 server.js），
  // 供 Dockerfile runtime 阶段直接 `node server.js` 启动，无需 node_modules。
  output: 'standalone',
  turbopack: {
    root: path.resolve(projectDir, '..'),
  },
  outputFileTracingRoot: path.resolve(projectDir, '..'),
};

export default nextConfig;