import { FormEvent, useEffect, useRef, useState } from "react";
import { HttpAgent } from "@ag-ui/client";
import { EventType } from "@ag-ui/core";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming: boolean;
  isToolCall?: boolean;
}

type AuthType = "none" | "bearer" | "apikey";

interface ConnectionConfig {
  url: string;
  authType: AuthType;
  authValue: string;
}

export default function ChatPage() {
  const [config, setConfig] = useState<ConnectionConfig>({
    url: "",
    authType: "bearer",
    authValue: "",
  });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const threadIdRef = useRef(crypto.randomUUID());
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const buildHeaders = (): Record<string, string> => {
    if (config.authType === "bearer" && config.authValue)
      return { Authorization: `Bearer ${config.authValue}` };
    if (config.authType === "apikey" && config.authValue)
      return { "X-API-Key": config.authValue };
    return {};
  };

  const sendMessage = (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || !config.url || isRunning) return;

    setInput("");
    setIsRunning(true);

    const userMsgId = crypto.randomUUID();
    const userMsg: ChatMessage = { id: userMsgId, role: "user", content: text, isStreaming: false };
    setMessages((prev) => [...prev, userMsg]);

    const history = [
      ...messages.map((m) => ({ id: m.id, role: m.role, content: m.content })),
      { id: userMsgId, role: "user" as const, content: text },
    ];

    const agent = new HttpAgent({ url: config.url, headers: buildHeaders() });
    let activeMsgId: string | null = null;

    agent
      .runAgent({
        runId: crypto.randomUUID(),
        threadId: threadIdRef.current,
        messages: history,
        tools: [],
        context: [],
        state: null,
      })
      .subscribe({
        next: (event) => {
          switch (event.type) {
            case EventType.TEXT_MESSAGE_START: {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const e = event as any;
              activeMsgId = e.messageId as string;
              setMessages((prev) => [
                ...prev,
                { id: activeMsgId!, role: "assistant", content: "", isStreaming: true },
              ]);
              break;
            }
            case EventType.TEXT_MESSAGE_CONTENT: {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const e = event as any;
              const msgId = (e.messageId as string) || activeMsgId;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId ? { ...m, content: m.content + (e.delta as string || "") } : m
                )
              );
              break;
            }
            case EventType.TEXT_MESSAGE_END: {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const e = event as any;
              const msgId = (e.messageId as string) || activeMsgId;
              setMessages((prev) =>
                prev.map((m) => (m.id === msgId ? { ...m, isStreaming: false } : m))
              );
              break;
            }
            case EventType.TOOL_CALL_START: {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const e = event as any;
              setMessages((prev) => [
                ...prev,
                {
                  id: e.toolCallId as string || crypto.randomUUID(),
                  role: "assistant",
                  content: `Calling tool: ${e.toolCallName as string || "unknown"}…`,
                  isStreaming: true,
                  isToolCall: true,
                },
              ]);
              break;
            }
            case EventType.TOOL_CALL_END: {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const e = event as any;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === (e.toolCallId as string) ? { ...m, isStreaming: false } : m
                )
              );
              break;
            }
            case EventType.RUN_FINISHED: {
              setIsRunning(false);
              break;
            }
            case EventType.RUN_ERROR: {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const e = event as any;
              const errText = (e.message as string) || "Agent reported an error";
              if (activeMsgId) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === activeMsgId ? { ...m, content: errText, isStreaming: false } : m
                  )
                );
              } else {
                setMessages((prev) => [
                  ...prev,
                  { id: crypto.randomUUID(), role: "assistant", content: errText, isStreaming: false },
                ]);
              }
              setIsRunning(false);
              break;
            }
          }
        },
        error: (err: Error) => {
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: `Connection error: ${err.message}`,
              isStreaming: false,
            },
          ]);
          setIsRunning(false);
        },
      });
  };

  const clearChat = () => {
    setMessages([]);
    threadIdRef.current = crypto.randomUUID();
  };

  return (
    <div className="chat-page">
      <aside className="config-panel">
        <p className="config-heading">Agent connection</p>

        <div className="form-group">
          <label htmlFor="agent-url">Agent URL</label>
          <input
            id="agent-url"
            type="url"
            placeholder="https://…vertexai.app/…"
            value={config.url}
            onChange={(e) => setConfig((c) => ({ ...c, url: e.target.value }))}
          />
        </div>

        <div className="form-group">
          <label htmlFor="auth-type">Authentication</label>
          <select
            id="auth-type"
            value={config.authType}
            onChange={(e) => setConfig((c) => ({ ...c, authType: e.target.value as AuthType }))}
          >
            <option value="none">None</option>
            <option value="bearer">Bearer token</option>
            <option value="apikey">API key</option>
          </select>
        </div>

        {config.authType !== "none" && (
          <div className="form-group">
            <label htmlFor="auth-value">
              {config.authType === "bearer" ? "Token" : "API key"}
            </label>
            <input
              id="auth-value"
              type="password"
              placeholder={config.authType === "bearer" ? "Bearer token" : "API key value"}
              value={config.authValue}
              onChange={(e) => setConfig((c) => ({ ...c, authValue: e.target.value }))}
            />
          </div>
        )}

        <button className="btn-secondary" onClick={clearChat}>
          Clear conversation
        </button>
      </aside>

      <div className="chat-area">
        <div className="messages-container">
          {messages.length === 0 && (
            <div className="empty-state">
              {config.url ? (
                <>
                  <strong>Ready to evaluate</strong>
                  Try: "every lakehouse in production must be assigned to a capacity" — or ask FabOps Copilot to list existing rules.
                </>
              ) : (
                <>
                  <strong>Connect to an agent</strong>
                  Enter the Vertex AI Agent Engine URL in the panel on the left to get started.
                </>
              )}
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`message message-${msg.role}${msg.isToolCall ? " message-tool" : ""}`}
            >
              <div className="message-role">
                {msg.role === "user" ? "You" : msg.isToolCall ? "Tool" : "Agent"}
              </div>
              <div className="message-content">
                {msg.content}
                {msg.isStreaming && <span className="cursor" />}
              </div>
            </div>
          ))}

          <div ref={messagesEndRef} />
        </div>

        <form className="input-bar" onSubmit={sendMessage}>
          <input
            type="text"
            placeholder={
              !config.url
                ? "Set an agent URL first…"
                : isRunning
                ? "Agent is working…"
                : "Describe a rule or ask about your Fabric governance…"
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={!config.url || isRunning}
          />
          <button type="submit" disabled={!input.trim() || !config.url || isRunning}>
            {isRunning ? "…" : "Send"}
          </button>
        </form>
      </div>
    </div>
  );
}
