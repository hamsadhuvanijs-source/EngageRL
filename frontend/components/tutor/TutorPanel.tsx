"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, getTutorMessages, sendTutorMessage } from "@/lib/api";
import type { TutorMessageOut } from "@/types/api";

export function TutorPanel({ chatId }: { chatId: string }) {
  const [messages, setMessages] = useState<TutorMessageOut[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getTutorMessages(chatId)
      .then(setMessages)
      .catch(() => setError("Couldn't load the tutor chat history."))
      .finally(() => setLoaded(true));
  }, [chatId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  const onSend = async () => {
    const content = input.trim();
    if (!content || sending) return;

    setError(null);
    setInput("");
    setSending(true);

    const optimisticUser: TutorMessageOut = {
      id: `pending-${Date.now()}`,
      chat_id: chatId,
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticUser]);

    try {
      const reply = await sendTutorMessage(chatId, content);
      setMessages((prev) => [...prev.filter((m) => m.id !== optimisticUser.id), reply.user_message, reply.assistant_message]);
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== optimisticUser.id));
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't reach the tutor. Is Ollama running locally?"
      );
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <aside className="tutor-panel">
      <div className="tutor-panel-header">
        <span>💬 Tutor</span>
        <span className="text-faint" style={{ fontSize: 11 }}>
          local · mistral
        </span>
      </div>

      <div className="tutor-panel-messages" ref={scrollRef}>
        {loaded && messages.length === 0 && (
          <p className="text-muted" style={{ fontSize: 13 }}>
            Ask me anything about this material — I can explain, quiz you, or clarify anything confusing.
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`tutor-message tutor-message-${m.role}`}>
            {m.content}
          </div>
        ))}
        {sending && <div className="tutor-message tutor-message-assistant tutor-message-typing">Thinking...</div>}
      </div>

      {error && <p className="error-text" style={{ fontSize: 12, padding: "0 14px" }}>{error}</p>}

      <div className="tutor-panel-input">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask a question..."
          rows={2}
          disabled={sending}
        />
        <button className="btn" onClick={onSend} disabled={sending || !input.trim()}>
          Send
        </button>
      </div>
    </aside>
  );
}
