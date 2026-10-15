import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

/**
 * Vitest 配置。
 *
 * 只测纯函数与无网络的展示组件（空状态渲染），所以环境用 jsdom、
 * 不需要 @vitejs/plugin-react（esbuild 按 tsconfig 的 jsx:react-jsx 转 JSX）。
 * 路径别名 @ 与 tsconfig 对齐，保证测试里能 import '@/...'。
 */
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
