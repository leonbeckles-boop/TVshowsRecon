// web/src/auth/AuthProvider.tsx
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { login as apiLogin, register as apiRegister, me as apiMe, setToken, clearToken, type User } from "../api";

type AuthCtx = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, password: string) => Promise<User>;
  logout: () => void;
};

const Ctx = createContext<AuthCtx>(null as any);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Restore session on mount
  useEffect(() => {
    (async () => {
      try {
        const u = await apiMe();
        setUser(u);
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
        setToken(tok.access_token);       // store token first
        const u = await apiMe();          // then hydrate user
        setUser(u);
        return u;
      },
      async register(email: string, password: string) {
        // Register only creates the user. Our backend returns a user object (201 Created),
        // not an access token. We then login separately to obtain the token.
        const created = await apiRegister(email, password);
        return created as unknown as User;
      },
      logout() {
        clearToken();
        setUser(null);
      },
    }),
    []
  );

  const value = useMemo<AuthCtx>(() => ({ user, loading, ...actions }), [user, loading, actions]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  return useContext(Ctx);
}