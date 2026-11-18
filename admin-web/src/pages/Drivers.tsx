import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowUpRight, Check, Copy, KeyRound, Phone, UserPlus, UsersRound, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Avatar, Empty, ErrorState, Loading, PageHeading, SearchField, StatusBadge, Vehicle } from '../components/ui';
import { useAuth } from '../hooks/useAuth';
import { useClock } from '../hooks/useClock';
import { displayState, useFeed } from '../hooks/useLiveFeed';
import { errorMessage, useResource } from '../hooks/useResource';
import { formatDateTime, searchKey } from '../lib/format';
import type { PairingCodeResult } from '../types';

const getDrivers = (signal: AbortSignal) => api.getDrivers(signal);

export function Drivers() {
  const { user } = useAuth();
  const isManager = user?.role === 'manager';
  const result = useResource(getDrivers);
  const { drivers: live, connection, settings } = useFeed();
  const now = useClock();
  const [search, setSearch] = useState('');
  const [panel, setPanel] = useState<'create' | 'pair' | null>(null);

  // Form thêm tài xế
  const [fullName, setFullName] = useState('');
  const [phone, setPhone] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [vehicleName, setVehicleName] = useState('');
  const [creatingDriver, setCreatingDriver] = useState(false);
  const [createError, setCreateError] = useState('');
  const [createdInfo, setCreatedInfo] = useState<string | null>(null);

  // Form tạo mã ghép xe
  const [pairVehicleId, setPairVehicleId] = useState('');
  const [expiresInMinutes, setExpiresInMinutes] = useState(60);
  const [creatingCode, setCreatingCode] = useState(false);
  const [pairError, setPairError] = useState('');
  const [pairResult, setPairResult] = useState<PairingCodeResult | null>(null);
  const [copiedCode, setCopiedCode] = useState(false);

  const vehicles = useMemo(() => {
    const map = new Map<string, string>();
    for (const driver of result.data ?? []) {
      if (driver.vehicleId && !map.has(driver.vehicleId)) {
        map.set(driver.vehicleId, driver.vehicleName);
      }
    }
    return [...map.entries()].map(([id, name]) => ({ id, name }));
  }, [result.data]);

  const query = searchKey(search);
  const drivers = useMemo(() => result.data?.filter((driver) =>
    !query || searchKey(`${driver.fullName} ${driver.vehicleName} ${driver.phone}`).includes(query)), [query, result.data]);
  const liveById = useMemo(() => new Map(live.map((driver) => [driver.driverId, driver])), [live]);

  async function handleCreateDriver(event: FormEvent) {
    event.preventDefault();
    if (creatingDriver) return;
    setCreatingDriver(true);
    setCreateError('');
    setCreatedInfo(null);
    try {
      const created = await api.createDriver({
        fullName: fullName.trim(),
        phone: phone.trim(),
        username: username.trim() || undefined,
        password: password || undefined,
        vehicleName: vehicleName.trim() || undefined,
      });
      const loginName = username.trim() || phone.trim();
      const loginPass = created.temporaryPassword || password || '(mật khẩu tạm thời)';
      setCreatedInfo(`Đã tạo tài xế ${created.fullName} · Tài khoản: ${loginName} / ${loginPass} (bắt buộc đổi mật khẩu lần đầu)`);
      setFullName('');
      setPhone('');
      setUsername('');
      setPassword('');
      setVehicleName('');
      result.retry();
    } catch (error) {
      setCreateError(errorMessage(error));
    } finally {
      setCreatingDriver(false);
    }
  }

  async function handleCreatePairingCode(event: FormEvent) {
    event.preventDefault();
    if (creatingCode) return;
    setCreatingCode(true);
    setPairError('');
    setCopiedCode(false);
    try {
      const codeRes = await api.createPairingCode({
        vehicleId: pairVehicleId || undefined,
        expiresInMinutes,
      });
      setPairResult(codeRes);
    } catch (error) {
      setPairError(errorMessage(error));
    } finally {
      setCreatingCode(false);
    }
  }

  async function copyCode(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedCode(true);
    } catch {
      setCopiedCode(false);
    }
  }

  return (
    <>
      <PageHeading
        title="Danh sách tài xế"
        description="Xem hồ sơ tài xế, xe được phân công và trạng thái giám sát."
        eyebrow={<><UsersRound size={14} aria-hidden /> ĐỘI XE</>}
        actions={isManager && (
          <div className="driver-admin-actions">
            <button
              type="button"
              className={`button button-small ${panel === 'create' ? 'button-primary' : 'button-secondary'}`}
              onClick={() => { setPanel(panel === 'create' ? null : 'create'); setCreateError(''); }}
            >
              <UserPlus size={15} aria-hidden /> Thêm tài xế
            </button>
            <button
              type="button"
              className={`button button-small ${panel === 'pair' ? 'button-primary' : 'button-secondary'}`}
              onClick={() => { setPanel(panel === 'pair' ? null : 'pair'); setPairError(''); }}
            >
              <KeyRound size={15} aria-hidden /> Tạo mã ghép xe
            </button>
          </div>
        )}
      />

      {isManager && panel === 'create' && (
        <section className="card panel page-section driver-admin-panel" aria-labelledby="create-driver-heading">
          <div className="filter-heading">
            <span className="icon-tile tone-green"><UserPlus size={18} aria-hidden /></span>
            <h2 id="create-driver-heading">Thêm tài khoản tài xế</h2>
            <button type="button" className="icon-button" aria-label="Đóng biểu mẫu thêm tài xế" onClick={() => setPanel(null)}>
              <X size={17} aria-hidden />
            </button>
          </div>
          <form onSubmit={(e) => void handleCreateDriver(e)} aria-busy={creatingDriver}>
            <div className="driver-admin-grid">
              <label>Họ và tên *
                <input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Ví dụ: Trần Văn Hùng" required disabled={creatingDriver} />
              </label>
              <label>Số điện thoại *
                <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Ví dụ: 0901234599" required disabled={creatingDriver} />
              </label>
              <label>Tên đăng nhập <span className="muted">(mặc định SĐT)</span>
                <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Ví dụ: driver6" autoCapitalize="none" spellCheck={false} disabled={creatingDriver} />
              </label>
              <label>Mật khẩu <span className="muted">(mặc định driver123)</span>
                <input type="text" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="driver123" disabled={creatingDriver} />
              </label>
              <label className="driver-admin-wide">Biển số / Tên xe <span className="muted">(tùy chọn)</span>
                <input value={vehicleName} onChange={(e) => setVehicleName(e.target.value)} placeholder="Ví dụ: 51B-678.90 - Giường nằm 40 chỗ" disabled={creatingDriver} />
              </label>
            </div>
            {createError && <p className="field-error driver-admin-feedback" role="alert">{createError}</p>}
            {createdInfo && <p className="driver-admin-success" role="status"><Check size={15} aria-hidden /> {createdInfo}</p>}
            <div className="driver-admin-submit">
              <button type="submit" className="button button-primary" disabled={creatingDriver}>
                <UserPlus size={16} aria-hidden /> {creatingDriver ? 'Đang tạo…' : 'Tạo tài khoản tài xế'}
              </button>
            </div>
          </form>
        </section>
      )}

      {isManager && panel === 'pair' && (
        <section className="card panel page-section driver-admin-panel" aria-labelledby="pairing-code-heading">
          <div className="filter-heading">
            <span className="icon-tile tone-green"><KeyRound size={18} aria-hidden /></span>
            <h2 id="pairing-code-heading">Tạo mã ghép xe 6 ký tự</h2>
            <button type="button" className="icon-button" aria-label="Đóng tạo mã ghép xe" onClick={() => setPanel(null)}>
              <X size={17} aria-hidden />
            </button>
          </div>
          <form onSubmit={(e) => void handleCreatePairingCode(e)} aria-busy={creatingCode}>
            <div className="driver-admin-grid">
              <label>Xe phân công
                <select value={pairVehicleId} onChange={(e) => setPairVehicleId(e.target.value)} disabled={creatingCode}>
                  <option value="">Tự chọn xe mặc định của nhà xe</option>
                  {vehicles.map((veh) => <option key={veh.id} value={veh.id}>{veh.name}</option>)}
                </select>
              </label>
              <label>Thời hạn mã
                <select value={expiresInMinutes} onChange={(e) => setExpiresInMinutes(Number(e.target.value))} disabled={creatingCode}>
                  <option value={15}>15 phút</option>
                  <option value={60}>60 phút</option>
                  <option value={1440}>24 giờ</option>
                </select>
              </label>
            </div>
            {pairError && <p className="field-error driver-admin-feedback" role="alert">{pairError}</p>}
            <div className="driver-admin-submit">
              <button type="submit" className="button button-primary" disabled={creatingCode}>
                <KeyRound size={16} aria-hidden /> {creatingCode ? 'Đang tạo mã…' : 'Tạo mã ghép xe'}
              </button>
            </div>
          </form>
          {pairResult && (
            <div className="pairing-result" role="status">
              <div>
                <span className="muted">Mã ghép xe cho tài xế:</span>
                <strong className="pairing-code">{pairResult.code}</strong>
                <small className="muted">Hết hạn lúc {formatDateTime(pairResult.expiresAt)} (GMT+7)</small>
              </div>
              <button type="button" className="button button-secondary button-small" onClick={() => void copyCode(pairResult.code)}>
                {copiedCode ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
                {copiedCode ? 'Đã sao chép' : 'Sao chép mã'}
              </button>
            </div>
          )}
        </section>
      )}

      <section className="card data-panel" aria-labelledby="driver-list-heading">
        <div className="data-panel-heading list-toolbar">
          <div><h2 id="driver-list-heading">Tài xế của đội xe</h2><p>{result.data ? `${drivers?.length ?? 0} / ${result.data.length} tài xế` : 'Thông tin đội xe'}</p></div>
          <SearchField value={search} onChange={setSearch} placeholder="Tìm tên, biển số hoặc số điện thoại…" />
        </div>
        {result.loading && <Loading />}
        {result.error && <ErrorState message={result.error} retry={result.retry} />}
        {drivers && (drivers.length ? (
          <><div className="driver-list-labels" aria-hidden><span>Tài xế / Xe</span><span>Điện thoại</span><span>Trạng thái</span><span /></div>
          <ul className="driver-list">{drivers.map((driver) => {
            const state = liveById.get(driver.id);
            return <li key={driver.id}>
              <Link className="driver-row" to={`/drivers/${encodeURIComponent(driver.id)}`}>
                <div className="driver-list-identity"><Avatar name={driver.fullName} id={driver.id} avatarUrl={driver.avatarUrl} />
                  <div><strong>{driver.fullName}</strong><Vehicle name={driver.vehicleName} /></div></div>
                <span className="driver-phone"><Phone size={14} aria-hidden />{driver.phone || '—'}</span>
                <StatusBadge state={state ? displayState(state, connection, now, settings.heartbeatIntervalSec) : 'UNCONFIRMED'} />
                <span className="driver-open"><ArrowUpRight size={17} aria-hidden /></span>
              </Link>
            </li>;
          })}</ul></>
        ) : <Empty title={result.data?.length ? 'Không tìm thấy tài xế phù hợp' : 'Chưa có tài xế'} description="Danh sách hiển thị các tài xế thuộc đội xe của bạn." />)}
      </section>
    </>
  );
}
