import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import zh from "./locales/zh.json";
import en from "./locales/en.json";

export const SUPPORTED_LANGUAGES = ["zh", "en"] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

export const LANGUAGE_LABELS: Record<Language, string> = {
  zh: "中文",
  en: "English",
};

const STORAGE_KEY = "coding-agent-language";

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      zh: { translation: zh },
      en: { translation: en },
    },
    fallbackLng: "zh",
    supportedLngs: SUPPORTED_LANGUAGES,

    detection: {
      // 优先顺序：localStorage → navigator
      order: ["localStorage", "navigator"],
      lookupLocalStorage: STORAGE_KEY,
      caches: ["localStorage"],
    },

    interpolation: {
      // React 已处理 XSS，不需要 i18next 再转义
      escapeValue: false,
    },

    // 开发时输出缺失 key 的警告
    debug: import.meta.env.DEV,

    // 复数形式（中文无复数，用 simple 规则）
    pluralSeparator: "_",
  });

export default i18n;

/** 获取当前语言（归一化到 'zh' 或 'en'） */
export function getCurrentLanguage(): Language {
  const lang = i18n.language.split("-")[0];
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(lang)
    ? (lang as Language)
    : "zh";
}

/** 切换语言 */
export async function changeLanguage(lang: Language): Promise<void> {
  await i18n.changeLanguage(lang);
}