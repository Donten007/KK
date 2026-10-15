'use client';

/**
 * Shell 顶栏的客户端包装：登录后补取用户与账套信息。
 *
 * access token 常驻内存（session-store 设计），SSR 阶段取不到，
 * 因此用户信息在挂载后拉一次 /auth/me 与 /tenants/current。
 * 拉取失败必须退回登录页而不是静默留白 ——
 * 老板看到空白页会以为系统坏了（省略比报错更伤信任）。
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiRequest } from '@/lib/api/client';
import { fetchCurrentUser } from '@/lib/api/auth';
import { getSession } from '@/lib/api/session-store';
import { Topbar } from './topbar';
import type { components } from '@/types/api';

type Tenant = components['schemas']['Tenant'];
type PendingItem = components['schemas']['PendingItem'];

export function WorkspaceShellClient() {
  const router = useRouter();
  const [user, setUser] = useState<components['schemas']['User'] | null>(null);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    if (!getSession()) {
      router.replace('/login');
      return;
    }

    let cancelled = false;

    void (async () => {
      const [me, tenantResult, pendingResult] = await Promise.all([
        fetchCurrentUser(),
        // 账套缺失不阻断页面 —— 顶栏只是少显示一个号，不该把人拦在门外
        apiRequest<Tenant>('/api/v1/tenants/current').catch(() => null),
        // 待确认角标：真实接口数据，禁假数据。端点未就绪/失败时按 0 处理（不显示角标）
        apiRequest<PendingItem[]>('/api/v1/pending').catch(() => []),
      ]);

      if (cancelled) return;
      if (!me) {
        router.replace('/login');
        return;
      }
      setUser(me);
      setTenant(tenantResult);
      setPendingCount(pendingResult.length);
    })();

    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <Topbar tenantCode={tenant?.code} tenantName={tenant?.name} user={user ?? undefined} pendingCount={pendingCount} />
  );
}