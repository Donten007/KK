'use client';

/**
 * 登录 / 注册表单。
 *
 * UIUX §7.2 反 Hero 模式：单一入口用 SegmentedControl 切「登录/注册」，
 * 不让用户在两个页面间跳。label 在上（--fg-2 13px），禁止 placeholder 当 label。
 *
 * BYOK 语境：注册表单**不放**任何充值/额度/套餐相关文案（功能不存在）。
 * API Key 在后续配置步骤渐进披露，不在首屏（UIUX §7.2）。
 */

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Field } from '@/components/ui/field';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { login, register } from '@/lib/api/auth';

type Mode = 'login' | 'register';

export function AuthForm() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>('login');

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [companyName, setCompanyName] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  function switchMode(next: Mode) {
    setMode(next);
    // 切模式必须清错误，否则上一模式的报错会挂在另一个模式的表单上
    setFormError(null);
    setEmailError(null);
    setPasswordError(null);
  }

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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
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
      if (error instanceof ApiError) {
        setFormError(error.message);
        // 凭证错误就地提示，不清空用户已填内容（重新输入是老板最烦的事）
        if (error.code === 1001) setPasswordError(error.message);
      } else {
        setFormError('出了点问题，请稍后重试。');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex w-full max-w-[380px] flex-col gap-[var(--space-6)]">
      {/* SegmentedControl：2 选 1，不占决策资源 */}
      <div
        role="tablist"
        aria-label="登录或注册"
        className="grid grid-cols-2 gap-[var(--space-1)] rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-2)] p-[var(--space-1)]"
      >
        {(['login', 'register'] as const).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={mode === key}
            onClick={() => switchMode(key)}
            className={[
              'min-h-[var(--control-h)] rounded-[var(--radius-sm)] px-[var(--space-3)]',
              'text-[var(--text-sm)]',
              'transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)]',
              mode === key
                ? 'bg-[var(--surface-3)] text-[var(--fg-1)] font-[var(--weight-medium)]'
                : 'text-[var(--fg-2)] hover:text-[var(--fg-1)]',
            ].join(' ')}
          >
            {key === 'login' ? '登录' : '注册'}
          </button>
        ))}
      </div>

      <div>
        <h1 className="text-[var(--text-xl)] font-[var(--weight-semibold)] tracking-[var(--tracking-tight)] text-[var(--fg-1)]">
          {mode === 'login' ? '登录' : '创建账号'}
        </h1>
        <p className="mt-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-2)]">
          {mode === 'login'
            ? '用注册时的邮箱登录。'
            : '注册后会为你的公司生成一个账套号，它就是你们的身份。'}
        </p>
      </div>

      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-[var(--space-4)]">
        <Field
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

        <Field
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
          <Field
            label="公司名称"
            name="company_name"
            autoComplete="organization"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            hint="填了之后，日报里会按这个名字称呼你的公司。"
          />
        ) : null}

        {/* 表单级错误：靠近提交点，紧贴出错来源 */}
        {formError ? (
          <p role="alert" className="text-[var(--text-sm)] text-[var(--danger)]">
            {formError}
          </p>
        ) : null}

        <Button type="submit" loading={submitting}>
          {mode === 'login' ? '登录' : '创建账号'}
        </Button>
      </form>

      <p className="text-[var(--text-xs)] text-[var(--muted)]">
        模型调用费用直接付给你自己的模型服务商，我们不经手。
      </p>
    </div>
  );
}