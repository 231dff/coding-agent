import { Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { LoginPage } from "./LoginPage";

interface RequireAuthProps {
  children: React.ReactNode;
}

/**
 * 路由守卫。未登录时渲染登录页。
 */
export function RequireAuth({ children }: RequireAuthProps) {
  const { user, initialized, config } = useAuth();

  // 认证被禁用：直接渲染
  if (config?.mode === "disabled") {
    return <>{children}</>;
  }

  // 配置未加载完：显示加载中
  if (!initialized) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // 未登录：显示登录页
  if (!user && config?.require_auth !== false) {
    return <LoginPage />;
  }

  return <>{children}</>;
}

/**
 * 需要指定角色的守卫。
 */
interface RequireRoleProps {
  role: "admin" | "developer" | "viewer";
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export function RequireRole({ role, children, fallback }: RequireRoleProps) {
  const { user } = useAuth();

  const ROLE_ORDER = { viewer: 0, developer: 1, admin: 2 };
  const userLevel = user
    ? Math.max(...user.roles.map((r) => ROLE_ORDER[r] ?? 0))
    : -1;

  if (userLevel < ROLE_ORDER[role]) {
    return (
      <>
        {fallback ?? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            需要 {role} 权限
          </div>
        )}
      </>
    );
  }

  return <>{children}</>;
}