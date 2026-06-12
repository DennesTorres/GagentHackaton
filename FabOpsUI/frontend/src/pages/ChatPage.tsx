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

export default function ChatPage() {
  const [ready, setReady] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const threadIdRef = useRef(crypto.randomUUID());
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then((data: { agent_url: string | null }) => {
        if (!data.agent_url) throw new Error('FABOPS environment variable not set.');
        setReady(true);
      })
      .catch((e: Error) => setConfigError(e.message));
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, currentStep]);

  const sendMessage = (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || !ready || isRunning) return;

    setInput("");
    setIsRunning(true);
    setCurrentStep("Thinking…");

    const userMsgId = crypto.randomUUID();
    const history = [
      ...messages.map(m => ({ id: m.id, role: m.role, content: m.content })),
      { id: userMsgId, role: "user" as const, content: text },
    ];

    setMessages(prev => [...prev, { id: userMsgId, role: "user", content: text, isStreaming: false }]);

    const agent = new HttpAgent({ url: '/api/agent', fetch: window.fetch.bind(window) });
    let activeMsgId: string | null = null;

    agent
      .run({
        runId: crypto.randomUUID(),
        threadId: threadIdRef.current,
        messages: history,
        tools: [],
        context: [],
        state: null,
      })
      .subscribe({
        next: (event) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const e = event as any;
          switch (event.type) {

            case EventType.TEXT_MESSAGE_START:
              setCurrentStep(null);
              activeMsgId = e.messageId as string;
              setMessages(prev => [...prev, { id: activeMsgId!, role: "assistant", content: "", isStreaming: true }]);
              break;

            case EventType.TEXT_MESSAGE_CONTENT: {
              const msgId = (e.messageId as string) || activeMsgId;
              setMessages(prev => prev.map(m =>
                m.id === msgId ? { ...m, content: m.content + (e.delta as string || "") } : m
              ));
              break;
            }

            case EventType.TEXT_MESSAGE_END: {
              const msgId = (e.messageId as string) || activeMsgId;
              setMessages(prev => prev.map(m =>
                m.id === msgId ? { ...m, isStreaming: false } : m
              ));
              break;
            }

            case EventType.TOOL_CALL_START: {
              const toolName = e.toolCallName as string || "tool";
              setCurrentStep(`Calling: ${toolName}`);
              setMessages(prev => [...prev, {
                id: e.toolCallId as string || crypto.randomUUID(),
                role: "assistant",
                content: `Calling tool: ${toolName}`,
                isStreaming: false,
                isToolCall: true,
              }]);
              break;
            }

            case EventType.RUN_FINISHED:
              setCurrentStep(null);
              setIsRunning(false);
              break;

            case EventType.RUN_ERROR: {
              const errText = (e.message as string) || "Agent reported an error";
              setCurrentStep(null);
              if (activeMsgId) {
                setMessages(prev => prev.map(m =>
                  m.id === activeMsgId ? { ...m, content: errText, isStreaming: false } : m
                ));
              } else {
                setMessages(prev => [...prev, { id: crypto.randomUUID(), role: "assistant", content: errText, isStreaming: false }]);
              }
              setIsRunning(false);
              break;
            }
          }
        },
        error: (err: Error) => {
          setCurrentStep(null);
          setMessages(prev => [...prev, {
            id: crypto.randomUUID(),
            role: "assistant",
            content: `Connection error: ${err.message}`,
            isStreaming: false,
          }]);
          setIsRunning(false);
        },
      });
  };

  const clearChat = () => {
    setMessages([]);
    setCurrentStep(null);
    threadIdRef.current = crypto.randomUUID();
  };

  return (
    <div className="chat-page">
      <div className="chat-area">
        <div className="messages-container">
          {configError && (
            <div className="empty-state">
              <strong>Agent not configured</strong>
              {configError}
            </div>
          )}

          {!configError && messages.length === 0 && !isRunning && (
            <div className="empty-state">
              <strong>Ready to evaluate</strong>
              Try: "every lakehouse in production must be assigned to a capacity" — or ask FabOps Copilot to list existing rules.
            </div>
          )}

          {messages.map(msg => (
            <div key={msg.id} className={`message message-${msg.role}${msg.isToolCall ? " message-tool" : ""}`}>
              <div className="message-role">{msg.role === "user" ? "You" : msg.isToolCall ? "Tool" : "Agent"}</div>
              <div className="message-content">
                {msg.content}
                {msg.isStreaming && <span className="cursor" />}
              </div>
            </div>
          ))}

          {currentStep && (
            <div className="message message-assistant">
              <div className="message-role">Agent</div>
              <div className="message-content thinking-bubble">
                <span className="thinking-label">{currentStep}</span>
                <span className="thinking-dots">
                  <span /><span /><span />
                </span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <form className="input-bar" onSubmit={sendMessage}>
          <input
            type="text"
            placeholder={isRunning ? "Agent is working…" : "Describe a rule or ask about your Fabric governance…"}
            value={input}
            onChange={e => setInput(e.target.value)}
            disabled={!ready || isRunning}
          />
          <button type="submit" disabled={!input.trim() || !ready || isRunning}>
            {isRunning ? "…" : "Send"}
          </button>
        </form>

        <div className="chat-actions">
          <button className="btn-secondary" onClick={clearChat}>Clear conversation</button>
        </div>
      </div>
    </div>
  );
}
