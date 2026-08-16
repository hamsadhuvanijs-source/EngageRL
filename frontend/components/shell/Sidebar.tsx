"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { listChats } from "@/lib/api";
import type { ChatOut } from "@/types/api";

export function Sidebar() {
  const pathname = usePathname();
  const [chats, setChats] = useState<ChatOut[]>([]);

  useEffect(() => {
    listChats()
      .then(setChats)
      .catch(() => setChats([]));
  }, [pathname]);

  return (
    <aside className="sidebar">
      <Link href="/" className="sidebar-brand">
        EngageRL
      </Link>

      <Link href="/chats/new" className="btn new-chat-btn">
        + New Chat
      </Link>

      <div className="chat-history">
        <div className="chat-history-label">History</div>
        {chats.length === 0 && <p className="chat-history-empty">No chats yet</p>}
        {chats.map((chat) => (
          <Link
            key={chat.id}
            href={`/chats/${chat.id}`}
            className={`chat-history-item ${pathname === `/chats/${chat.id}` ? "active" : ""}`}
          >
            {chat.title || "Untitled chat"}
          </Link>
        ))}
      </div>
    </aside>
  );
}
