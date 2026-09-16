import { useCallback, useEffect, useRef, useState } from "react";
import { chatStreamRaw } from "@/api/client";
import { parseSSEStream } from "@/api/sse";
import type { StreamEvent } from "@/api/types";

interface UseAgentStreamOptions {
  onEvent?: (event: StreamEvent) => void;
  onError?: (error: Error) => void;
  onDone?: () => void;
  onApprovalRequired?: (event: StreamEvent & { type: "approval_required" }) => void;
}

interface UseAgentStreamResult {
  events: StreamEvent[];
  isStreaming: boolean;
  error: Error | null;
  send: (message: string, sessionId?: string) => Promise<void>;
  abort: () => void;
  clear: () => void;
}

export function useAgentStream(
  options: UseAgentStreamOptions = {}
): UseAgentStreamResult {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const optionsRef = useRef(options);

  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const send = useCallback(async (message: string, sessionId = "") => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsStreaming(true);
    setError(null);

    try {
      const resp = await chatStreamRaw(
        { message, session_id: sessionId },
        controller.signal
      );

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
      }

      for await (const event of parseSSEStream(resp)) {
        if (controller.signal.aborted) break;

        setEvents((prev) => [...prev, event]);
        optionsRef.current.onEvent?.(event);

        if (event.type === "approval_required") {
          optionsRef.current.onApprovalRequired?.(event);
        }

        if (event.type === "done") {
          optionsRef.current.onDone?.();
          break;
        }
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        return;
      }
      const err = e instanceof Error ? e : new Error(String(e));
      setError(err);
      optionsRef.current.onError?.(err);
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, []);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  const clear = useCallback(() => {
    setEvents([]);
    setError(null);
  }, []);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return { events, isStreaming, error, send, abort, clear };
}