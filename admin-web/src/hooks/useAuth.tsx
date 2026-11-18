import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api, isMock } from '../api';
import { ApiError, SESSION_EXPIRED, SESSION_REFRESHED } from '../api/contract';
import { readStorage, writeStorage } from '../lib/storage';
import type { LoginResult, User } from '../types';

const storageKey = `predrive:${isMock ? 'demo' : 'http'}:access-token`;
const refreshStorageKey = `predrive:${isMock ? 'demo' : 'http'}:refresh-token`;
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
  api.setRefreshToken?.(null);
  writeStorage(storageKey, null, 'sessionStorage');
  writeStorage(refreshStorageKey, null, 'sessionStorage');
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
    const refreshed = (ev: Event) => {
      const detail = (ev as CustomEvent<LoginResult>).detail;
      if (detail?.accessToken) {
        writeStorage(storageKey, detail.accessToken, 'sessionStorage');
        writeStorage(refreshStorageKey, detail.refreshToken ?? null, 'sessionStorage');
        if (detail.user && allowed(detail.user)) {
          setUser(detail.user);
        }
      }
    };
    window.addEventListener(SESSION_EXPIRED, expired);
    window.addEventListener(SESSION_REFRESHED, refreshed);

    const token = readStorage<string | null>(storageKey, null, 'sessionStorage');
    const savedRefresh = readStorage<string | null>(refreshStorageKey, null, 'sessionStorage');
    if (token) {
      api.setAccessToken(token);
      api.setRefreshToken?.(savedRefresh);
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
      window.removeEventListener(SESSION_REFRESHED, refreshed);
    };
  }, []);

  const auth: Auth = {
    user, loading,
    async login(username, password) {
      const session = await api.login(username, password);
      if (!allowed(session.user)) throw new ApiError('Tài khoản tài xế không có quyền truy cập bảng điều hành.', 403);
      api.setAccessToken(session.accessToken);
      api.setRefreshToken?.(session.refreshToken ?? null);
      writeStorage(storageKey, session.accessToken, 'sessionStorage');
      writeStorage(refreshStorageKey, session.refreshToken ?? null, 'sessionStorage');
      setUser(session.user);
    },
    logout() {
      const savedRefresh = readStorage<string | null>(refreshStorageKey, null, 'sessionStorage');
      void api.logout?.(savedRefresh);
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
