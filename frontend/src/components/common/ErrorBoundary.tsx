import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** 自定义回退 UI */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** 错误上报回调 */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * 错误边界。
 *
 * 捕获子组件的渲染错误，防止整个应用白屏。
 *
 * React 要求错误边界必须是 class 组件。
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // 开发时打印到 Console
    if (import.meta.env.DEV) {
      console.error("[ErrorBoundary] 捕获错误:", error);
      console.error("[ErrorBoundary] 组件栈:", errorInfo.componentStack);
    }
    // 生产环境可以上报到 Sentry / 自建日志
    this.props.onError?.(error, errorInfo);
  }

  reset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.reset);
      }
      return <DefaultFallback error={this.state.error} reset={this.reset} />;
    }
    return this.props.children;
  }
}

interface DefaultFallbackProps {
  error: Error;
  reset: () => void;
}

function DefaultFallback({ error, reset }: DefaultFallbackProps) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="max-w-md space-y-4 text-center">
        <AlertTriangle className="mx-auto h-12 w-12 text-destructive" />

        <div>
          <h2 className="text-lg font-semibold">页面出现错误</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            组件渲染失败，已捕获以避免白屏。
          </p>
        </div>

        <pre className="max-h-40 overflow-auto rounded-md border bg-muted p-3 text-left font-mono text-xs">
          {error.message}
        </pre>

        <div className="flex justify-center gap-2">
          <button
            onClick={reset}
            className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs text-white transition-colors hover:opacity-90"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            重试
          </button>
          <button
            onClick={() => window.location.reload()}
            className="rounded-md border px-3 py-1.5 text-xs transition-colors hover:bg-muted"
          >
            刷新页面
          </button>
        </div>
      </div>
    </div>
  );
}