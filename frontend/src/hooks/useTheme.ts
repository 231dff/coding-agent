import { useThemeStore } from "@/stores/themeStore";
import type { ThemeMode } from "@/stores/themeStore";

export function useTheme() {
  const mode = useThemeStore((s) => s.mode);
  const resolved = useThemeStore((s) => s.resolved);
  const setMode = useThemeStore((s) => s.setMode);

  return {
    mode,
    resolved,
    isDark: resolved === "dark",
    setMode,
    toggleLightDark: () => {
      setMode(resolved === "dark" ? "light" : "dark");
    },
  };
}

export type { ThemeMode };