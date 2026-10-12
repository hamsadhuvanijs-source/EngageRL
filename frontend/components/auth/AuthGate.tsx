"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Sidebar } from "@/components/shell/Sidebar";

const PUBLIC_PATHS = ["/login", "/register"];

export function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    if (!loading && !user && !isPublic) router.replace("/login");
    if (!loading && user && isPublic) router.replace("/");
  }, [loading, user, isPublic, router]);

  if (loading) {
    return <div className="auth-loading">Loading…</div>;
  }

  if (isPublic) {
    return <div className="app-main">{children}</div>;
  }

  if (!user) {
    return null; // redirect in flight
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">{children}</div>
    </div>
  );
}
