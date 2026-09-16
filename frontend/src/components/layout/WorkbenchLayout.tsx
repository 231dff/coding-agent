import { Group, Panel, Separator } from "react-resizable-panels";
import { useEffect, useState } from "react";
import {
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface WorkbenchLayoutProps {
  sidebar: React.ReactNode;
  main: React.ReactNode;
  artifact: React.ReactNode;
}

const STORAGE_KEY = "workbench-layout";

export function WorkbenchLayout({ sidebar, main, artifact }: WorkbenchLayoutProps) {
  const [leftOpen, setLeftOpen] = useState<boolean>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? JSON.parse(saved).leftOpen : true;
  });
  const [rightOpen, setRightOpen] = useState<boolean>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? JSON.parse(saved).rightOpen : true;
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ leftOpen, rightOpen }));
  }, [leftOpen, rightOpen]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-9 items-center gap-2 border-b px-2">
        <button
          onClick={() => setLeftOpen((v: boolean) => !v)}
          className="rounded-md p-1 hover:bg-muted"
          title={leftOpen ? "折叠会话栏" : "展开会话栏"}
        >
          {leftOpen ? (
            <PanelLeftClose className="h-3.5 w-3.5" />
          ) : (
            <PanelLeftOpen className="h-3.5 w-3.5" />
          )}
        </button>

        <div className="flex-1" />

        <button
          onClick={() => setRightOpen((v: boolean) => !v)}
          className="rounded-md p-1 hover:bg-muted"
          title={rightOpen ? "折叠产物栏" : "展开产物栏"}
        >
          {rightOpen ? (
            <PanelRightClose className="h-3.5 w-3.5" />
          ) : (
            <PanelRightOpen className="h-3.5 w-3.5" />
          )}
        </button>
      </header>

      <Group orientation="horizontal" className="flex-1">
        {leftOpen && (
          <>
            <Panel defaultSize="18%" minSize="12%" maxSize="30%">
              <aside className="h-full overflow-hidden border-r bg-muted/20">
                {sidebar}
              </aside>
            </Panel>
            <Separator
              className={cn(
                "w-1 bg-border transition-colors",
                "hover:bg-accent data-[resize-handle-state=drag]:bg-accent"
              )}
            />
          </>
        )}

        <Panel minSize="40%">
          <main className="h-full overflow-hidden">{main}</main>
        </Panel>

        {rightOpen && (
          <>
            <Separator
              className={cn(
                "w-1 bg-border transition-colors",
                "hover:bg-accent data-[resize-handle-state=drag]:bg-accent"
              )}
            />
            <Panel defaultSize="28%" minSize="20%" maxSize="45%">
              <aside className="h-full overflow-hidden border-l bg-muted/20">
                {artifact}
              </aside>
            </Panel>
          </>
        )}
      </Group>
    </div>
  );
}