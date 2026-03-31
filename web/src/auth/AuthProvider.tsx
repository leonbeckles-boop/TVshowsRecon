// web/src/auth/AuthProvider.tsx
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  login as apiLogin,
  register as apiRegister,
  me as apiMe,
  touchAuth,
  clearToken,
  type User,
} from "../api";

type AuthCtx = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, password: string) => Promise<User>;
  logout: () => void;
};

const Ctx = createContext<AuthCtx>(null as any);

async function touchLastSeenThrottled() {
  try {
    const last = localStorage.getItem("last_touch");
    const now = Date.now();

    if (last && now - Number(last) < 30 * 60 * 1000) return;

    await touchAuth();
    localStorage.setItem("last_touch", String(now));
  } catch (err) {
    console.warn("Failed to update last seen", err);
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const u = await apiMe();
        setUser(u);
        await touchLastSeenThrottled();
      } catch {
        clearToken();
        setUser(null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const actions = useMemo(
    () => ({
      async login(email: string, password: string) {
        const tok = await apiLogin(email, password);
        if (!tok?.access_token) throw new Error("No access token returned");

        const u = await apiMe();
        setUser(u);
        await touchLastSeenThrottled();
        return u;
      },

      async register(email: string, password: string) {
        const created = await apiRegister(email, password);
        return created as unknown as User;
      },

      logout() {
        clearToken();
        setUser(null);
        try {
          localStorage.removeItem("last_touch");
        } catch {
          // ignore
        }
      },
    }),
    []
  );

  const value = useMemo<AuthCtx>(
    () => ({ user, loading, ...actions }),
    [user, loading, actions]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  return useContext(Ctx);
}