import { useRef, useState, KeyboardEvent } from "react";
import { Send, Square, Lock } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import { canWrite } from "@/types/auth";

interface ComposerProps {
  onSend: (message: string) => void;
  onAbort: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export function Composer({
  onSend,
  onAbort,
  isStreaming,
  disabled,
}: ComposerProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { user } = useAuth();

  const writable = canWrite(user);
  const canSend = value.trim().length > 0 && !isStreaming && !disabled && writable;

  function handleSend() {
    if (!canSend) return;
    onSend(value.trim());
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput(e: React.FormEvent<HTMLTextAreaElement>) {
    const el = e.currentTarget;
    setValue(el.value);
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  if (!writable) {
    return (
      <div className="border-t bg-background p-3">
        <div className="flex items-center gap-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
          <Lock className="h-3.5 w-3.5" />
          <span>{t("chat.readonlyHint")}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="border-t bg-background p-3">
      <div
        className={cn(
          "flex items-end gap-2 rounded-lg border bg-muted/30 p-2",
          "focus-within:border-accent focus-within:bg-background transition-colors"
        )}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={t("chat.inputPlaceholder")}
          rows={1}
          disabled={disabled}
          className={cn(
            "flex-1 resize-none bg-transparent text-sm outline-none",
            "placeholder:text-muted-foreground",
            "max-h-[200px] overflow-y-auto"
          )}
        />

        {isStreaming ? (
          <button
            onClick={onAbort}
            className="rounded-md bg-destructive p-2 text-white hover:opacity-90"
            title={t("chat.abort")}
          >
            <Square className="h-4 w-4 fill-current" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!canSend}
            className={cn(
              "rounded-md p-2 transition-colors",
              canSend
                ? "bg-accent text-white hover:opacity-90"
                : "cursor-not-allowed bg-muted text-muted-foreground"
            )}
            title={t("chat.send")}
          >
            <Send className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}