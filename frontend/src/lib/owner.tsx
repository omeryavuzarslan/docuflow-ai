import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";

import { setApiOwner } from "../api/client";

const STORAGE_KEY = "docuflow.owner";

function readStored(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || "demo";
  } catch {
    return "demo";
  }
}

const OwnerContext = createContext<{ owner: string; setOwner: (o: string) => void } | null>(null);

/** Development stand-in for sign-in: which owner's data the UI shows. */
export function OwnerProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [owner, setOwnerState] = useState(() => {
    const stored = readStored();
    setApiOwner(stored);
    return stored;
  });

  function setOwner(next: string) {
    setApiOwner(next);
    setOwnerState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* private mode: fine, just not remembered */
    }
    queryClient.clear(); // never show one owner's cached data to another
  }

  return <OwnerContext.Provider value={{ owner, setOwner }}>{children}</OwnerContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useOwner() {
  const value = useContext(OwnerContext);
  if (!value) throw new Error("useOwner outside OwnerProvider");
  return value;
}
