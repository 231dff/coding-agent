import { WifiOff, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useOnlineStatus } from "@/hooks/useOnlineStatus";

export function OfflineBanner() {
  const { t } = useTranslation();
  const online = useOnlineStatus();

  if (online) return null;

  return (
    <div className="flex items-center justify-center gap-2 border-b border-amber-300 bg-amber-100 px-4 py-1.5 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/60 dark:text-amber-100">
      <WifiOff className="h-3.5 w-3.5 shrink-0" />
      <span>{t("offline.message")}</span>
      <button
        onClick={() => window.location.reload()}
        className="ml-1 flex items-center gap-1 rounded border border-amber-400 px-1.5 py-0.5 transition-colors hover:bg-amber-200 dark:border-amber-600 dark:hover:bg-amber-900/50"
      >
        <RefreshCw className="h-3 w-3" />
        {t("offline.reload")}
      </button>
    </div>
  );
}