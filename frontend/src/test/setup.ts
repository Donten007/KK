/**
 * 测试全局设置：把 jest-dom 的 DOM 断言扩展进 vitest 的 expect。
 * 提供 toBeInTheDocument() 等语义化断言（比 queryByText().not.toBeNull() 更可读）。
 */
import '@testing-library/jest-dom/vitest';
