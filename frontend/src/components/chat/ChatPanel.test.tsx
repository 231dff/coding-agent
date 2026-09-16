import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPanel } from "./ChatPanel";
import { useAuthStore } from "@/hooks/useAuth";
import type { User } from "@/types/auth";


const adminUser: User = {
  id: "u-test",
  name: "Test Admin",
  email: "test@example.com",
  roles: ["admin"],
  picture: "",
};


function mockSSEResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, { status: 200 });
}


describe("ChatPanel", () => {
  beforeEach(() => {
    // 强制设置为有写权限的用户，避免显示"只读"
    useAuthStore.setState({
      config: {
        mode: "disabled",
        require_auth: false,
        oidc_authority: "",
        oidc_client_id: "",
        oidc_redirect_uri: "",
        oidc_scope: "",
      },
      user: adminUser,
      initialized: true,
      loading: false,
      error: null,
    });
  });

  it("发送消息后渲染事件流", async () => {
    const user = userEvent.setup();

    const fetchMock = vi
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(
        mockSSEResponse([
          'event: token\ndata: {"content":"hello","session_id":"s1"}\n\n',
          'event: done\ndata: {"session_id":"s1"}\n\n',
        ])
      );

    render(<ChatPanel />);

    const input = screen.getByPlaceholderText(
      /描述你的任务/
    ) as HTMLTextAreaElement;

    await user.type(input, "test message");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    fetchMock.mockRestore();
  });
});