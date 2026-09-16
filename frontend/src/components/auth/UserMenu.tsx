import { useState, useRef, useEffect } from "react";
import { LogOut, User as  Shield } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

export function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  if (!user) return null;

  

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-md px-1.5 py-1 hover:bg-muted"
      >
        {user.picture ? (
          <img
            src={user.picture}
            alt={user.name}
            className="h-6 w-6 rounded-full"
          />
        ) : (
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-accent/15 text-[10px] font-medium text-accent">
            {user.name.slice(0, 1).toUpperCase()}
          </div>
        )}
        <span className="hidden text-xs sm:inline">{user.name}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-9 z-30 w-56 rounded-md border bg-popover p-1 shadow-md">
          {/* 用户信息 */}
          <div className="border-b px-2 py-2">
            <div className="flex items-center gap-2">
              {user.picture ? (
                <img src={user.picture} alt="" className="h-8 w-8 rounded-full" />
              ) : (
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/15 text-xs font-medium text-accent">
                  {user.name.slice(0, 1).toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium">{user.name}</div>
                {user.email && (
                  <div className="truncate text-[10px] text-muted-foreground">
                    {user.email}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* 角色 */}
          <div className="px-2 py-1.5">
            <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              角色
            </div>
            <div className="flex flex-wrap gap-1">
              {user.roles.map((r) => (
                <span
                  key={r}
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-[10px] font-medium",
                    r === "admin" && "border-red-300 bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300",
                    r === "developer" && "border-blue-300 bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300",
                    r === "viewer" && "border-gray-300 bg-gray-50 text-gray-700 dark:bg-gray-900/50 dark:text-gray-300",
                  )}
                >
                  {r === "admin" && <Shield className="mr-0.5 inline h-2.5 w-2.5" />}
                  {r}
                </span>
              ))}
            </div>
          </div>

          {/* 分隔 */}
          <div className="my-1 h-px bg-border" />

          {/* 登出 */}
          <button
            onClick={() => {
              setOpen(false);
              logout();
            }}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs text-destructive hover:bg-destructive/10"
          >
            <LogOut className="h-3 w-3" />
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}