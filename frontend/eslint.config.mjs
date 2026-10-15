import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

/**
 * ESLint 配置（Next.js 16 原生 flat config）。
 *
 * 不用 FlatCompat 包装 —— 它与 eslint-config-next@16 的原生 flat 导出会
 * 形成循环引用，导致 "Converting circular structure to JSON" 启动崩溃。
 */
const config = [
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts'],
  },
  {
    rules: {
      // 未使用参数以 _ 前缀豁免（_req 之类是接口签名要求，不能删）
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
];

export default config;