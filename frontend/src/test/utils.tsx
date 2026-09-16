import { type ReactElement, type ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n";


// ============================================================
// 强制 i18n 语言（每次 render 前）
//
// 根因：其他测试可能调用 changeLanguage 切换语言，
// 导致后续测试的断言失败。这里每次渲染前重置为中文。
// ============================================================
function ensureChinese() {
  if (i18n.language !== "zh") {
    // 同步切换（i18next 的 changeLanguage 是异步的，但这里
    // 只做本地资源切换，不涉及网络，可以同步完成）
    void i18n.changeLanguage("zh");
  }
}


export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}


interface ProviderOptions extends Omit<RenderOptions, "wrapper"> {
  queryClient?: QueryClient;
}


export function renderWithProviders(
  ui: ReactElement,
  options: ProviderOptions = {}
) {
  const { queryClient = createTestQueryClient(), ...renderOptions } = options;

  ensureChinese();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </I18nextProvider>
    );
  }

  return {
    ...render(ui, { wrapper: Wrapper, ...renderOptions }),
    queryClient,
  };
}


export function flushMicrotasks(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}


export function sseEvent(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}


export function mockSseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}