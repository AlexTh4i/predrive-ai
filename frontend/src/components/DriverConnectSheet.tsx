import { useState } from 'react';
import type { FormEvent } from 'react';
import {
  CheckCircle2,
  CloudOff,
  Link2,
  LogOut,
  RefreshCw,
  Server,
  ShieldCheck,
  UserRound,
  Wifi,
  X,
} from 'lucide-react';
import type { ServerHealthStatus, SyncStatus } from '../hooks/useDriverSync';
import type { DriverAuthSession, DriverMode } from '../types/m3';

interface DriverConnectSheetProps {
  open: boolean;
  onClose: () => void;
  auth: DriverAuthSession | null;
  mode: DriverMode;
  onModeChange: (mode: DriverMode) => void;
  serverUrl: string;
  healthStatus: ServerHealthStatus;
  healthError: string | null;
  pendingCount: number;
  syncStatus: SyncStatus;
  syncError: string | null;
  isMonitoring: boolean;
  onSaveAndTestServer: (url: string) => Promise<boolean>;
  onLogin: (username: string, password: string, serverUrl?: string) => Promise<DriverAuthSession>;
  onPair: (code: string) => Promise<DriverAuthSession>;
  onLogout: () => void;
  onFlushNow: () => Promise<void>;
}

export function DriverConnectSheet(props: DriverConnectSheetProps) {
  if (!props.open) return null;
  return <DriverConnectSheetInner {...props} />;
}

function DriverConnectSheetInner({
  onClose,
  auth,
  mode,
  onModeChange,
  serverUrl,
  healthStatus,
  healthError,
  pendingCount,
  syncStatus,
  syncError,
  isMonitoring,
  onSaveAndTestServer,
  onLogin,
  onPair,
  onLogout,
  onFlushNow,
}: DriverConnectSheetProps) {
  const [urlInput, setUrlInput] = useState(serverUrl);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [pairCode, setPairCode] = useState('');
  const [consentChecked, setConsentChecked] = useState(true);
  const [busyAction, setBusyAction] = useState<'server' | 'login' | 'pair' | 'sync' | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  async function handleTestServer() {
    setBusyAction('server');
    setFormError(null);
    setFormSuccess(null);
    const ok = await onSaveAndTestServer(urlInput);
    if (ok) {
      setFormSuccess('Đã kết nối thành công tới máy chủ PreDrive.');
    }
    setBusyAction(null);
  }

  async function handleLoginSubmit(event: FormEvent) {
    event.preventDefault();
    if (busyAction) return;
    setBusyAction('login');
    setFormError(null);
    setFormSuccess(null);
    try {
      const session = await onLogin(username, password, urlInput);
      setUsername('');
      setPassword('');
      setFormSuccess(`Đã đăng nhập: ${session.user.fullName}`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Đăng nhập thất bại.');
    } finally {
      setBusyAction(null);
    }
  }

  async function handlePairSubmit(event: FormEvent) {
    event.preventDefault();
    if (busyAction) return;
    if (!consentChecked) {
      setFormError('Vui lòng xác nhận đồng ý giám sát trước khi ghép xe.');
      return;
    }
    setBusyAction('pair');
    setFormError(null);
    setFormSuccess(null);
    try {
      const updated = await onPair(pairCode);
      setPairCode('');
      setFormSuccess(
        `Đã ghép xe ${updated.vehicleName ?? ''} (${updated.organizationName ?? 'Nhà xe'})`,
      );
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Ghép xe thất bại.');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSyncNow() {
    setBusyAction('sync');
    setFormError(null);
    setFormSuccess(null);
    await onFlushNow();
    setBusyAction(null);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="connect-sheet-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="grab-scope w-full max-w-md max-h-[88dvh] overflow-y-auto bg-white text-[#1C1C1C] rounded-t-3xl sm:rounded-3xl grab-sheet-shadow p-5"
        style={{ paddingBottom: 'max(1.5rem, env(safe-area-inset-bottom))' }}
      >
        <div className="flex items-center justify-between gap-3 pb-3 border-b border-[#E8E8E8]">
          <div>
            <h2 id="connect-sheet-title" className="text-lg font-bold text-[#1C1C1C]">
              Kết nối văn phòng
            </h2>
            <p className="text-xs text-[#5E6366] mt-0.5">
              Cấu hình máy chủ, đăng nhập tài xế và ghép xe
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng thiết lập kết nối"
            className="w-10 h-10 rounded-full border border-[#E8E8E8] flex items-center justify-center text-[#1C1C1C] hover:bg-slate-100"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 1. Chế độ hoạt động */}
        <div className="mt-4">
          <span className="text-xs font-bold uppercase tracking-wide text-[#5E6366]">
            Chế độ giám sát
          </span>
          <div className="grid grid-cols-2 gap-2 mt-2">
            <button
              type="button"
              disabled={isMonitoring}
              onClick={() => onModeChange('online')}
              className={`px-3 py-2.5 rounded-xl border text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 ${
                mode === 'online'
                  ? 'border-[#00B14F] bg-[#E5F7ED] text-[#009A44]'
                  : 'border-[#E8E8E8] bg-white text-[#5E6366]'
              }`}
            >
              <Wifi className="w-4 h-4 shrink-0" />
              <span>Kết nối văn phòng</span>
            </button>
            <button
              type="button"
              disabled={isMonitoring}
              onClick={() => onModeChange('offline_demo')}
              className={`px-3 py-2.5 rounded-xl border text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 ${
                mode === 'offline_demo'
                  ? 'border-[#1C1C1C] bg-slate-100 text-[#1C1C1C]'
                  : 'border-[#E8E8E8] bg-white text-[#5E6366]'
              }`}
            >
              <CloudOff className="w-4 h-4 shrink-0" />
              <span>Dùng thử offline</span>
            </button>
          </div>
          {isMonitoring && (
            <p className="text-[11px] text-[#5E6366] mt-1.5">
              Dừng giám sát trước khi đổi chế độ kết nối.
            </p>
          )}
        </div>

        {/* 2. Địa chỉ Máy chủ */}
        <div className="mt-4 p-3.5 rounded-2xl bg-[#F8F9FA] border border-[#E8E8E8]">
          <label
            htmlFor="driver-server-url"
            className="flex items-center gap-1.5 text-xs font-bold text-[#1C1C1C]"
          >
            <Server className="w-4 h-4 text-[#00B14F]" />
            <span>Địa chỉ Máy chủ Backend</span>
          </label>
          <div className="flex gap-2 mt-2">
            <input
              id="driver-server-url"
              type="url"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="http://192.168.1.100:8000"
              autoCapitalize="none"
              spellCheck={false}
              className="flex-1 min-w-0 h-10 px-3 rounded-xl border border-[#CED8D3] bg-white text-sm text-[#1C1C1C]"
            />
            <button
              type="button"
              disabled={busyAction === 'server'}
              onClick={() => void handleTestServer()}
              className="h-10 px-3 rounded-xl bg-white border border-[#CED8D3] text-xs font-bold text-[#1C1C1C] hover:border-[#00B14F] disabled:opacity-60 shrink-0"
            >
              {busyAction === 'server' ? 'Đang thử...' : 'Kiểm tra'}
            </button>
          </div>
          {healthStatus === 'ok' && (
            <p className="text-xs text-[#009A44] font-medium mt-1.5 flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>Máy chủ sẵn sàng</span>
            </p>
          )}
          {healthStatus === 'error' && healthError && (
            <p className="text-xs text-[#E5372B] mt-1.5">{healthError}</p>
          )}
        </div>

        {/* Thông báo lỗi / thành công */}
        {formError && (
          <div
            role="alert"
            className="mt-3 p-3 rounded-xl bg-[#FDECEA] border border-[#F2B4AD] text-xs font-medium text-[#A42120]"
          >
            {formError}
          </div>
        )}
        {formSuccess && (
          <div
            role="status"
            className="mt-3 p-3 rounded-xl bg-[#E5F7ED] border border-[#A5E0BE] text-xs font-medium text-[#087340]"
          >
            {formSuccess}
          </div>
        )}

        {/* 3. Đăng nhập / Hồ sơ & Ghép xe */}
        {!auth || syncStatus === 'auth_expired' ? (
          <form onSubmit={(e) => void handleLoginSubmit(e)} className="mt-4 space-y-3">
            {syncStatus === 'auth_expired' && (
              <p className="text-xs font-medium text-[#E5372B]">
                {syncError ?? 'Phiên đăng nhập hết hạn, hãy đăng nhập lại để tiếp tục đồng bộ.'}
              </p>
            )}
            <div className="flex items-center gap-1.5 text-xs font-bold text-[#1C1C1C]">
              <UserRound className="w-4 h-4 text-[#00B14F]" />
              <span>Đăng nhập tài khoản Tài xế</span>
            </div>
            <div>
              <label htmlFor="driver-username" className="block text-xs font-semibold text-[#5E6366] mb-1">
                Tên đăng nhập hoặc SĐT
              </label>
              <input
                id="driver-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Ví dụ: driver1"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                required
                className="w-full h-11 px-3 rounded-xl border border-[#CED8D3] bg-white text-sm text-[#1C1C1C]"
              />
            </div>
            <div>
              <label htmlFor="driver-password" className="block text-xs font-semibold text-[#5E6366] mb-1">
                Mật khẩu
              </label>
              <input
                id="driver-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Nhập mật khẩu"
                autoComplete="current-password"
                required
                className="w-full h-11 px-3 rounded-xl border border-[#CED8D3] bg-white text-sm text-[#1C1C1C]"
              />
            </div>
            <p className="text-[11px] text-[#5E6366]">
              Tài khoản mẫu trên máy chủ M3: <code className="font-semibold">driver1</code> /{' '}
              <code className="font-semibold">driver123</code>
            </p>
            <button
              type="submit"
              disabled={busyAction === 'login'}
              className="w-full h-11 rounded-full bg-[#00B14F] hover:bg-[#009A44] text-white text-sm font-bold transition-colors disabled:opacity-60"
            >
              {busyAction === 'login' ? 'Đang đăng nhập...' : 'Đăng nhập'}
            </button>
          </form>
        ) : (
          <div className="mt-4 space-y-4">
            {/* Thông tin tài xế đang đăng nhập */}
            <div className="p-3.5 rounded-2xl border border-[#E8E8E8] bg-white space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-1.5 text-sm font-bold text-[#1C1C1C]">
                    <ShieldCheck className="w-4 h-4 text-[#00B14F]" />
                    <span>{auth.user.fullName}</span>
                  </div>
                  <p className="text-xs text-[#5E6366] mt-0.5">
                    {auth.vehicleName ? `Xe: ${auth.vehicleName}` : 'Chưa ghép xe mới trong phiên này'}
                  </p>
                  {auth.organizationName && (
                    <p className="text-[11px] text-[#5E6366]">{auth.organizationName}</p>
                  )}
                </div>
                <button
                  type="button"
                  disabled={isMonitoring}
                  onClick={onLogout}
                  className="px-2.5 py-1.5 rounded-lg border border-[#E8E8E8] text-xs font-semibold text-[#E5372B] hover:bg-[#FDECEA] flex items-center gap-1 disabled:opacity-50"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Đăng xuất</span>
                </button>
              </div>

              {/* Hàng đợi offline */}
              <div className="pt-2 border-t border-[#E8E8E8] flex items-center justify-between gap-2 text-xs">
                <span className="text-[#5E6366]">
                  Hàng đợi chưa gửi:{' '}
                  <strong className={pendingCount > 0 ? 'text-[#F5A623]' : 'text-[#009A44]'}>
                    {pendingCount}
                  </strong>
                </span>
                {pendingCount > 0 && (
                  <button
                    type="button"
                    disabled={busyAction === 'sync'}
                    onClick={() => void handleSyncNow()}
                    className="px-2.5 py-1 rounded-lg bg-[#E5F7ED] text-[#009A44] font-semibold flex items-center gap-1 disabled:opacity-60"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${busyAction === 'sync' ? 'animate-spin' : ''}`} />
                    <span>Đồng bộ ngay</span>
                  </button>
                )}
              </div>
              {syncError && <p className="text-[11px] text-[#F5A623]">{syncError}</p>}
            </div>

            {/* Ghép xe bằng mã 6 ký tự */}
            <form onSubmit={(e) => void handlePairSubmit(e)} className="p-3.5 rounded-2xl bg-[#F8F9FA] border border-[#E8E8E8] space-y-2.5">
              <div className="flex items-center gap-1.5 text-xs font-bold text-[#1C1C1C]">
                <Link2 className="w-4 h-4 text-[#00B14F]" />
                <span>Ghép xe bằng mã 6 ký tự</span>
              </div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={pairCode}
                  onChange={(e) => setPairCode(e.target.value.toUpperCase())}
                  placeholder="VD: PAIR01"
                  maxLength={10}
                  autoCapitalize="characters"
                  spellCheck={false}
                  required
                  className="flex-1 min-w-0 h-10 px-3 rounded-xl border border-[#CED8D3] bg-white text-sm font-mono uppercase tracking-wider text-[#1C1C1C]"
                />
                <button
                  type="submit"
                  disabled={busyAction === 'pair' || !pairCode.trim()}
                  className="h-10 px-3.5 rounded-xl bg-[#00B14F] hover:bg-[#009A44] text-white text-xs font-bold disabled:opacity-60 shrink-0"
                >
                  {busyAction === 'pair' ? 'Đang ghép...' : 'Ghép xe'}
                </button>
              </div>
              <label className="flex items-start gap-2 text-[11px] text-[#5E6366] cursor-pointer leading-snug">
                <input
                  type="checkbox"
                  checked={consentChecked}
                  onChange={(e) => setConsentChecked(e.target.checked)}
                  className="mt-0.5 accent-[#00B14F]"
                />
                <span>
                  Tôi đồng ý bật camera giám sát dấu hiệu buồn ngủ &amp; gửi cảnh báo an toàn về văn phòng nhà xe.
                </span>
              </label>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
