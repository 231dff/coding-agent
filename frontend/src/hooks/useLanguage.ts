import { useTranslation } from "react-i18next";
import { useCallback } from "react";
import {
  changeLanguage,
  getCurrentLanguage,
  LANGUAGE_LABELS,
  SUPPORTED_LANGUAGES,
  type Language,
} from "@/i18n";

export function useLanguage() {
  const { i18n } = useTranslation();
  const current = getCurrentLanguage();

  const setLanguage = useCallback(async (lang: Language) => {
    await changeLanguage(lang);
  }, []);

  return {
    current,
    available: SUPPORTED_LANGUAGES,
    labels: LANGUAGE_LABELS,
    setLanguage,
    /** 别名：i18n 的 t 函数 */
    t: i18n.t.bind(i18n),
  };
}