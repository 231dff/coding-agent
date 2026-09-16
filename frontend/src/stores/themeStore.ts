import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

interface ThemeState {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
  syncSystem: () => void;
}

const MEDIA_QUERY = "(prefers-color-scheme: dark)";

function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  if (typeof window.matchMedia !== "function") return "light";
  try {
    const mql = window.matchMedia(MEDIA_QUERY);
    if (!mql || typeof mql.matches !== "boolean") return "light";
    return mql.matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

function resolveTheme(mode: ThemeMode): ResolvedTheme {
  return mode === "system" ? getSystemTheme() : mode;
}

function applyThemeToDOM(theme: ResolvedTheme): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", theme === "dark" ? "#0d1117" : "#ffffff");
  }
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: "system",
      resolved: getSystemTheme(),

      setMode: (mode) => {
        const resolved = resolveTheme(mode);
        applyThemeToDOM(resolved);
        set({ mode, resolved });
      },

      syncSystem: () => {
        const { mode } = get();
        if (mode !== "system") return;
        const resolved = getSystemTheme();
        applyThemeToDOM(resolved);
        set({ resolved });
      },
    }),
    {
      name: "coding-agent-theme",
      partialize: (state) => ({ mode: state.mode }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          const resolved = resolveTheme(state.mode);
          applyThemeToDOM(resolved);
          state.resolved = resolved;
        }
      },
    }
  )
);

export function initTheme(): () => void {
  const store = useThemeStore.getState();
  const resolved = resolveTheme(store.mode);
  applyThemeToDOM(resolved);
  useThemeStore.setState({ resolved });

  if (typeof window === "undefined") return () => {};

  const media = window.matchMedia(MEDIA_QUERY);
  const handler = () => {
    useThemeStore.getState().syncSystem();
  };
  media.addEventListener("change", handler);

  return () => {
    media.removeEventListener("change", handler);
  };
}