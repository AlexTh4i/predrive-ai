import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api, isMock } from '../api';
import { ApiError, SESSION_EXPIRED } from '../api/contract';
import { readStorage, writeStorage } from '../lib/storage';
import type { User } from '../types';

const storageKey = `predrive:${isMock ? 'demo' : 'http'}:access-token`;
const allowed = (user: User) => user.role === 'manager' || user.role === 'dispatcher';

interface Auth {
  user: User | null;
  loading: boolean;
  login(username: string, password: string): Promise<void>;
  logout(): void;
}

const AuthContext = createContext<Auth | null>(null);

function clearSession() {
  api.setAccessToken(null);
  writeStorage(storageKey, null, 'sessionStorage');
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    const expired = () => {
      clearSession();
      setUser(null);
    };
    window.addEventListener(SESSION_EXPIRED, expired);
    const token = readStorage<string | null>(storageKey, null, 'sessionStorage');
    if (token) {
      api.setAccessToken(token);
      api.me(controller.signal).then((current) => {
        if (controller.signal.aborted) return;
        if (allowed(current)) setUser(current);
        else clearSession();
      }).catch(() => {
        if (!controller.signal.aborted) clearSession();
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    } else {
      setLoading(false);
    }
    return () => {
      controller.abort();
      window.removeEventListener(SESSION_EXPIRED, expired);
    };
  }, []);

  const auth: Auth = {
    user, loading,
    async login(username, password) {
      const session = await api.login(username, password);
      if (!allowed(session.user)) throw new ApiError('Tài khoản tài xế không có quyền truy cập bảng điều hành.', 403);
      api.setAccessToken(session.accessToken);
      writeStorage(storageKey, session.accessToken, 'sessionStorage');
      setUser(session.user);
    },
    logout() {
      clearSession();
      setUser(null);
    },
  };
  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error('Thiếu AuthProvider');
  return auth;
}
