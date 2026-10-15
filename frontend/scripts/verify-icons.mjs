/**
 * 图标名存在性核验（SPEC「坑 9」的防线）。
 *
 * 为什么必须脚本核验而不是查文档站：
 * Lucide 里大量图标**文件存在但没有 PascalCase 导出**，
 * 文档站 lucide.dev 却照常显示。照着文档站写 import 会直接 build 失败。
 * design-tokens.json brokenNamesDoNotUse 列的5 个名字全是这类
 * （Filter → ListFilter、CircleHelp → BadgeQuestionMark、Building2 → Building 等）。
 *
 * 做法：静态解析源码里所有 `from 'lucide-react'` 的具名导入，
 * 再到真实包的导出表里逐个核对。任一不存在即失败。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const SRC = join(process.cwd(), 'src');

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (['.ts', '.tsx'].includes(extname(full))) out.push(full);
  }
  return out;
}

const IMPORT_RE = /import\s+(?:type\s+)?\{([^}]+)\}\s*from\s*['"]lucide-react['"]/g;

const files = walk(SRC);
const used = new Map(); // name -> [file]

for (const file of files) {
  const src = readFileSync(file, 'utf8');
  for (const match of src.matchAll(IMPORT_RE)) {
    const names = match[1]
      .split(',')
      .map((n) => n.trim().replace(/^type\s+/, '').split(/\s+as\s+/)[0].trim())
      .filter(Boolean);
    for (const name of names) {
      if (!used.has(name)) used.set(name, []);
      used.get(name).push(file);
    }
  }
}

/** 静态 type-only 导入（如 type LucideIcon）不在运行时导出里，跳过 */
const TYPE_ONLY = new Set(['LucideIcon', 'LucideProps']);

let pkg;
try {
  pkg = require('lucide-react');
} catch {
  console.error('FAIL: 无法加载 lucide-react，请先 npm install');
  process.exit(1);
}

const missing = [];
for (const [name, locations] of used) {
  if (TYPE_ONLY.has(name)) continue;
  if (!(name in pkg)) {
    missing.push({ name, locations });
  }
}

if (missing.length > 0) {
  console.error(`FAIL: ${missing.length} 个图标名在 lucide-react 中不存在:`);
  for (const m of missing) {
    console.error(`  ${m.name}`);
    for (const loc of m.locations) console.error(`      ${loc}`);
  }
  process.exit(1);
}

console.log(`PASS: ${used.size - [...used.keys()].filter((n) => TYPE_ONLY.has(n)).length} 个图标名全部存在于 lucide-react`);