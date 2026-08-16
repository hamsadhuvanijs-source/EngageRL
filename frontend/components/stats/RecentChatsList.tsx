import Link from "next/link";

import type { ChatOut } from "@/types/api";

export function RecentChatsList({ chats }: { chats: ChatOut[] }) {
  if (chats.length === 0) {
    return <p className="text-muted">No chats yet. Start a new one to begin studying.</p>;
  }

  return (
    <div className="source-chips">
      {chats.map((chat) => (
        <Link href={`/chats/${chat.id}`} className="source-chip" key={chat.id} style={{ textDecoration: "none" }}>
          <span style={{ color: "var(--text)" }}>{chat.title || "Untitled chat"}</span>
          <span className="text-muted" style={{ fontSize: 12 }}>
            {new Date(chat.updated_at).toLocaleDateString()}
          </span>
        </Link>
      ))}
    </div>
  );
}
