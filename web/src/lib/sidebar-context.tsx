"use client";

import { createContext, useContext, useCallback, type ReactNode } from "react";

const SidebarCtx = createContext<{ toggle: () => void }>({
  toggle: () => {},
});

export function SidebarProvider({ children }: { children: ReactNode }) {
  const toggle = useCallback(() => {
    document.documentElement.classList.toggle("sidebar-collapsed");
  }, []);

  return (
    <SidebarCtx.Provider value={{ toggle }}>
      {children}
    </SidebarCtx.Provider>
  );
}

export function useSidebar() {
  return useContext(SidebarCtx);
}
