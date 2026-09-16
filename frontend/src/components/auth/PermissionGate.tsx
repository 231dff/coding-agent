import { useAuth } from "@/hooks/useAuth";
import type { Role } from "@/types/auth";

interface PermissionGateProps {
  /** 需要的最小角色 */
  minRole?: Role;
  /** 或指定任意角色（满足其一） */
  anyRole?: Role[];
  /** 允许时渲染 */
  children: React.ReactNode;
  /** 不允许时渲染 */
  fallback?: React.ReactNode;
}

/**
 * 基于角色的条件渲染。用于按钮级别权限控制。
 */
export function PermissionGate({
  minRole,
  anyRole,
  children,
  fallback = null,
}: PermissionGateProps) {
  const { user } = useAuth();

  if (!user) return <>{fallback}</>;

  if (anyRole && anyRole.length > 0) {
    const ok = anyRole.some((r) => user.roles.includes(r));
    return <>{ok ? children : fallback}</>;
  }

  if (minRole) {
    const ORDER: Record<Role, number> = { viewer: 0, developer: 1, admin: 2 };
    const userLevel = Math.max(...user.roles.map((r) => ORDER[r] ?? 0));
    const ok = userLevel >= ORDER[minRole];
    return <>{ok ? children : fallback}</>;
  }

  return <>{children}</>;
}