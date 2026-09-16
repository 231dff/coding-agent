import type { StreamEvent } from "@/api/types";

export function EventDebugList({ events }: { events: StreamEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="text-center text-sm text-muted-foreground">
        <p className="text-lg font-medium">Coding Agent</p>
        <p className="mt-2">描述一个任务，Agent 会读取代码、修改文件、运行测试</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {events.map((event, i) => (
        <div
          key={i}
          className="rounded-md border bg-muted/30 p-2 font-mono text-xs"
        >
          <div className="mb-1 font-semibold text-accent">{event.type}</div>
          <pre className="whitespace-pre-wrap break-all">
            {JSON.stringify(event, null, 2)}
          </pre>
        </div>
      ))}
    </div>
  );
}