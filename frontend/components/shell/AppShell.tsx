import type { ReactNode } from "react";

import { AuthGate } from "@/components/auth/AuthGate";
import { AuthProvider } from "@/components/auth/AuthProvider";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <AuthGate>{children}</AuthGate>
    </AuthProvider>
  );
}
