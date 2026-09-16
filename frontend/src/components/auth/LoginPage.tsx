import { useState } from "react";
import { Loader2, Shield, User as UserIcon, Eye } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

/**
 * 登录页。
 *
 * mock 模式：三个预设账号，点击即登录。
 * oidc 模式：跳转到 OIDC provider（此页只显示一个按钮）。
 */
export function LoginPage() {
  const { config, loginWithToken, loading, error } = useAuth();
  const [selected, setSelected] = useState<string>("");

  if (!config) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // OIDC 模式：重定向到 provider
  if (config.mode === "oidc") {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-sm space-y-4 text-center">
          <Shield className="mx-auto h-12 w-12 text-accent" />
          <h1 className="text-xl font-semibold">Coding Agent</h1>
          <p className="text-sm text-muted-foreground">
            请通过企业 SSO 登录
          </p>
          <button
            onClick={() => {
              // 完整实现：跳转到 OIDC provider 的 authorize 端点
              window.location.href = `${config.oidc_authority}/authorize?` +
                `client_id=${config.oidc_client_id}&` +
                `redirect_uri=${encodeURIComponent(config.oidc_redirect_uri)}&` +
                `response_type=code&` +
                `scope=${encodeURIComponent(config.oidc_scope)}`;
            }}
            className="w-full rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white hover:opacity-90"
          >
            使用 SSO 登录
          </button>
        </div>
      </div>
    );
  }

  // Mock 模式：显示预设账号
  const MOCK_ACCOUNTS = [
    {
      token: "mock-admin-token",
      name: "Admin User",
      email: "admin@example.com",
      role: "admin",
      description: "完整权限，可管理所有会话",
      icon: Shield,
      color: "text-red-600 dark:text-red-400",
    },
    {
      token: "mock-dev-token",
      name: "Developer",
      email: "dev@example.com",
      role: "developer",
      description: "可发消息、编辑文件、审批工具",
      icon: UserIcon,
      color: "text-blue-600 dark:text-blue-400",
    },
    {
      token: "mock-viewer-token",
      name: "Viewer",
      email: "viewer@example.com",
      role: "viewer",
      description: "只读，不能发消息或审批",
      icon: Eye,
      color: "text-gray-600 dark:text-gray-400",
    },
  ];

  async function handleLogin(token: string) {
    setSelected(token);
    try {
      await loginWithToken(token);
    } catch (e) {
      // error 已写入 store
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md space-y-5">
        <div className="text-center">
          <Shield className="mx-auto h-10 w-10 text-accent" />
          <h1 className="mt-3 text-xl font-semibold">Coding Agent</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            选择账号以体验不同权限
          </p>
        </div>

        {error && (
          <div className="rounded-md border border-destructive bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error.message}
          </div>
        )}

        <div className="space-y-2">
          {MOCK_ACCOUNTS.map((acc) => {
            const Icon = acc.icon;
            const isSelected = selected === acc.token;
            return (
              <button
                key={acc.token}
                onClick={() => handleLogin(acc.token)}
                disabled={loading}
                className={cn(
                  "flex w-full items-start gap-3 rounded-lg border bg-background p-3 text-left transition-colors",
                  isSelected
                    ? "border-accent bg-accent/5"
                    : "hover:border-accent/50 hover:bg-muted/30",
                  loading && !isSelected && "cursor-not-allowed opacity-50"
                )}
              >
                <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", acc.color)} />

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{acc.name}</span>
                    <span className={cn(
                      "rounded-full border px-1.5 py-0.5 text-[10px]",
                      acc.role === "admin" && "border-red-300 bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300",
                      acc.role === "developer" && "border-blue-300 bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300",
                      acc.role === "viewer" && "border-gray-300 bg-gray-50 text-gray-700 dark:bg-gray-900/50 dark:text-gray-300",
                    )}>
                      {acc.role}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    {acc.description}
                  </div>
                </div>

                {loading && isSelected && (
                  <Loader2 className="mt-0.5 h-4 w-4 animate-spin" />
                )}
              </button>
            );
          })}
        </div>

        <div className="text-center text-[10px] text-muted-foreground">
          当前为开发模式，实际部署时使用企业 SSO
        </div>
      </div>
    </div>
  );
}