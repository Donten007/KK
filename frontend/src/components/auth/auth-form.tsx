'use client';

/**
 * 登录 / 注册表单（营销级玻璃卡容器，UIUX-marketing §4）。
 *
 * **业务行为与 Phase 2 骨架版完全一致**（校验 / 提交 / 错误码处理不动），
 * 只换视觉容器与错误呈现：
 *   - mode 由路由决定（/login 与 /register 各挂一份），Segmented 切换 = 页面互跳；
 *   - 错误三通道（§4.5）：红边 + CircleAlert 图标 + 具体文案，不只红边；
 *   - 网络失败（§9）：卡内内联错误条 + 重试按钮（--radius-md 次级，非胶囊），
 *     不用 toast；
 *   - 登录失败（1002）按拍板口径：保留邮箱（高频输入），只清密码；
 *     文案「邮箱或密码不正确」（spec v1.1.1 §9，后端 auth_service 同源）。
 *
 * BYOK 语境：注册表单**不放**任何充值/额度/套餐相关文案（功能不存在）。
 */

import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { CircleAlert, LoaderCircle } from 'lucide-react';
import { MarketingField } from '@/components/auth/marketing-field';
import { ApiError } from '@/lib/api/client';
import { login, register } from '@/lib/api/auth';

type Mode = 'login' | 'register';

const MODE_TABS: ReadonlyArray<{ key: Mode; href: string; label: string }> = [
  { key: 'login', href: '/login', label: '登录' },
  { key: 'register', href: '/register', label: '注册' },
];

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [companyName, setCompanyName] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [networkError, setNetworkError] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  function validate(): boolean {
    let ok = true;
    // 邮箱格式：不引入 Zod 客户端全量 schema（Phase 2 骨架），
    // 但**不能只靠后端报错**——老板不该靠 400 学格式。
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setEmailError('请填写完整的邮箱地址。');
      ok = false;
    } else {
      setEmailError(null);
    }

    // SPEC §5 auth/register：password minLength 8
    if (password.length < 8) {
      setPasswordError('密码至少 8 位。');
      ok = false;
    } else {
      setPasswordError(null);
    }
    return ok;
  }

  /** 提交逻辑与骨架版一致；抽出来供表单提交与网络失败后的「重试」共用 */
  async function submit() {
    setFormError(null);
    setNetworkError(false);
    if (!validate()) return;

    setSubmitting(true);
    try {
      if (mode === 'login') {
        await login({ email: email.trim(), password });
      } else {
        await register({
          email: email.trim(),
          password,
          ...(companyName.trim() ? { company_name: companyName.trim() } : {}),
        });
      }
      router.replace('/');
    } catch (error) {
      if (error instanceof ApiError && error.isNetworkError) {
        // §9 网络失败：内联错误条 + 重试，不用 toast
        setFormError('连不上服务器，检查网络后重试。');
        setNetworkError(true);
      } else if (error instanceof ApiError) {
        if (mode === 'login' && error.code === 1002) {
          // 登录失败口径（spec v1.1.1 §4.5/§9 + 总监拍板）：登录语境下后端 1002
          // 就是凭证错误（auth_service 抛「邮箱或密码不正确」）。客户端 ERROR_MESSAGES
          // 会把 1002 覆盖成「登录已失效」，在登录表单语境不成立，这里按 spec 落文案。
          // 保留邮箱（高频输入），只清密码（安全惯例 + 只清密码口径）。
          setPasswordError('邮箱或密码不正确。');
          setPassword('');
        } else {
          setFormError(error.message);
          // 后端校验错误就地提示，不清空用户已填内容（重新输入是老板最烦的事）
          if (error.code === 1001) setPasswordError(error.message);
        }
      } else {
        setFormError('连不上服务器，检查网络后重试。');
        setNetworkError(true);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submit();
  }

  return (
    <div className="flex w-full flex-col gap-[var(--space-6)]">
      {/* SegmentedControl（沿用现有结构）：/login 与 /register 互跳 */}
      <div
        role="tablist"
        aria-label="登录或注册"
        className="grid grid-cols-2 gap-[var(--space-1)] rounded-[var(--radius-md)] border border-[var(--mkt-glass-border)] bg-[var(--mkt-glass-bg)] p-[var(--space-1)]"
      >
        {MODE_TABS.map((tab) => (
          <Link
            key={tab.key}
            href={tab.href}
            role="tab"
            aria-selected={mode === tab.key}
            className={[
              'flex min-h-[44px] items-center justify-center rounded-[var(--radius-sm)] px-[var(--space-3)] text-[var(--text-sm)]',
              'transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)]',
              mode === tab.key
                ? 'border border-[var(--mkt-input-border)] bg-[var(--mkt-input-bg)] font-[var(--weight-medium)] text-[var(--mkt-fg-1)]'
                : 'border border-transparent text-[var(--mkt-fg-muted)] hover:text-[var(--mkt-fg-1)]',
            ].join(' ')}
          >
            {tab.label}
          </Link>
        ))}
      </div>

      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-[var(--space-4)]">
        <MarketingField
          label="邮箱"
          type="email"
          name="email"
          autoComplete="email"
          inputMode="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={emailError}
          placeholder="name@company.com"
        />

        <MarketingField
          label="密码"
          type="password"
          name="password"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={passwordError}
          hint={mode === 'register' ? '至少 8 位。' : undefined}
        />

        {mode === 'register' ? (
          <MarketingField
            label="公司名称"
            name="company_name"
            autoComplete="organization"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            hint="填了之后，日报里会按这个名字称呼你的公司。"
          />
        ) : null}

        {/* 表单级错误（§9）：靠近提交点；网络失败带重试按钮（--radius-md，非胶囊） */}
        {formError ? (
          <div
            aria-live="polite"
            className="mkt-error-bar flex items-start gap-[var(--space-2)] rounded-[var(--radius-md)] border border-[var(--mkt-danger)] p-[var(--space-3)]"
          >
            <CircleAlert
              size={16}
              strokeWidth={1.5}
              className="mt-[2px] shrink-0 text-[var(--mkt-danger)]"
              aria-hidden="true"
            />
            <div className="flex flex-col items-start gap-[var(--space-2)]">
              <p className="text-[var(--text-sm)] text-[var(--mkt-danger)]">{formError}</p>
              {networkError ? (
                <button
                  type="button"
                  onClick={() => void submit()}
                  className="min-h-[44px] rounded-[var(--radius-md)] border border-[var(--mkt-input-border)] bg-transparent px-[var(--space-4)] text-[var(--text-sm)] text-[var(--mkt-fg-1)] transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)] hover:bg-[var(--mkt-input-bg)] active:bg-[var(--mkt-input-bg)]"
                >
                  重试
                </button>
              ) : null}
            </div>
          </div>
        ) : null}

        {/* CTA 白胶囊（§4.3）：本页唯一 pill。loading 态按 spec 换「正在验证…」
            + LoaderCircle——营销页 spec 覆盖工作台 Button「loading 不变文案」规则 */}
        <button
          type="submit"
          disabled={submitting}
          aria-busy={submitting || undefined}
          className="mkt-cta flex w-full items-center justify-center gap-[var(--space-2)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? (
            <>
              <LoaderCircle size={16} strokeWidth={1.5} className="icon-spin" aria-hidden="true" />
              正在验证…
            </>
          ) : mode === 'login' ? (
            '登录'
          ) : (
            '创建团队'
          )}
        </button>
      </form>

      <p className="text-[var(--text-xs)] text-[var(--mkt-fg-muted)]">
        模型调用费用直接付给你自己的模型服务商，我们不经手。
      </p>
    </div>
  );
}
