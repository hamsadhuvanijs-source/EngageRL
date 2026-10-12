"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { listChats } from "@/lib/api";
import type { ChatOut } from "@/types/api";

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [chats, setChats] = useState<ChatOut[]>([]);

  useEffect(() => {
    listChats()
      .then(setChats)
      .catch(() => setChats([]));
  }, [pathname]);

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

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

      {user && (
        <div className="sidebar-user">
          <span className="sidebar-user-email">{user.display_name || user.email}</span>
          <button type="button" className="btn sidebar-logout-btn" onClick={handleLogout}>
            Log out
          </button>
        </div>
      )}
    </aside>
  );
}
