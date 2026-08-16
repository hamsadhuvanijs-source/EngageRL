"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { PendingSourceInput, SourceInputTabs } from "@/components/chat/SourceInputTabs";
import { addFileSource, addLinkSource, addTextSource, createChat } from "@/lib/api";

type PendingSource = PendingSourceInput & { localId: string };

const TYPE_LABELS: Record<PendingSourceInput["type"], string> = {
  pdf: "PDF",
  txt: "TXT",
  youtube: "YouTube",
  website: "Website",
  pasted_text: "Text",
};

export function SourceComposer() {
  const router = useRouter();
  const [pending, setPending] = useState<PendingSource[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onAdd = (input: PendingSourceInput) => {
    setPending((prev) => [...prev, { ...input, localId: crypto.randomUUID() }]);
  };

  const onRemove = (localId: string) => {
    setPending((prev) => prev.filter((p) => p.localId !== localId));
  };

  const onSubmit = async () => {
    if (pending.length === 0) return;
    setIsSubmitting(true);
    setError(null);

    try {
      const chat = await createChat();

      for (const source of pending) {
        if (source.type === "pdf" || source.type === "txt") {
          await addFileSource(chat.id, source.file);
        } else if (source.type === "youtube" || source.type === "website") {
          await addLinkSource(chat.id, source.type, source.url);
        } else {
          await addTextSource(chat.id, source.text);
        }
      }

      router.push(`/chats/${chat.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong creating this chat.");
      setIsSubmitting(false);
    }
  };

  return (
    <div>
      <h1>New Chat</h1>
      <p className="text-muted">Add 2-3 reference sources on one topic, then start learning.</p>

      <SourceInputTabs onAdd={onAdd} />

      {pending.length > 0 && (
        <div className="source-chips">
          {pending.map((source) => (
            <div className="source-chip" key={source.localId}>
              <span>
                <span className="source-chip-type">{TYPE_LABELS[source.type]}</span>
                {source.label}
              </span>
              <button className="source-chip-remove" onClick={() => onRemove(source.localId)}>
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <button className="btn" onClick={onSubmit} disabled={pending.length === 0 || isSubmitting}>
        {isSubmitting ? "Creating..." : "Create Chat"}
      </button>

      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
