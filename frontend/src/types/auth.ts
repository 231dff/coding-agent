export type Role = "admin" | "developer" | "viewer";
export type AuthMode = "mock" | "oidc" | "disabled";

export interface User {
  id: string;
  name: string;
  email: string;
  roles: Role[];
  picture: string;
}

export interface AuthConfig {
  mode: AuthMode;
  require_auth: boolean;
  oidc_authority: string;
  oidc_client_id: string;
  oidc_redirect_uri: string;
  oidc_scope: string;
}

/** 判断用户是否有某个角色 */
export function hasRole(user: User | null, role: Role): boolean {
  if (!user) return false;
  return user.roles.includes(role);
}

/** 返回用户的最高优先级角色 */
export function primaryRole(user: User | null): Role {
  if (!user) return "viewer";
  if (user.roles.includes("admin")) return "admin";
  if (user.roles.includes("developer")) return "developer";
  return "viewer";
}

/** 是否有写权限 */
export function canWrite(user: User | null): boolean {
  const role = primaryRole(user);
  return role === "admin" || role === "developer";
}

/** 是否是管理员 */
export function isAdmin(user: User | null): boolean {
  return hasRole(user, "admin");
}