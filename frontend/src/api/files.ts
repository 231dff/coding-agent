const API_BASE = import.meta.env.VITE_API_URL ?? "";

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size?: number;
}

export interface TreeResponse {
  path: string;
  entries: FileEntry[];
}

export interface ContentResponse {
  path: string;
  content: string;
  size: number;
}

export async function fetchTree(path = "."): Promise<TreeResponse> {
  const resp = await fetch(`${API_BASE}/api/files/tree?path=${encodeURIComponent(path)}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  return resp.json();
}

export async function fetchFileContent(path: string): Promise<ContentResponse> {
  const resp = await fetch(`${API_BASE}/api/files/content?path=${encodeURIComponent(path)}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  return resp.json();
}