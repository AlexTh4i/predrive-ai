import { useCallback, useState } from 'react';
import { Bell, BellRing, BusFront, CalendarDays, ChevronDown, CircleAlert, RadioTower, ShieldAlert, Volume2, VolumeX, WifiOff } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../api';
import { AlertListItem } from '../components/AlertListItem';
import { HourlyAlertChart } from '../components/Charts';
import { DriverCard } from '../components/DriverCard';
import { StatTile } from '../components/StatTile';
import { Empty, ErrorState, Loading, PageHeading, SearchField, SectionHeading, TextLink, statusLabel } from '../components/ui';
import type { Alarm } from '../hooks/useAlarm';
import { useAuth } from '../hooks/useAuth';
import { useClock } from '../hooks/useClock';
import { displayState, useFeed } from '../hooks/useLiveFeed';
import type { DisplayState } from '../hooks/useLiveFeed';
import { useResource } from '../hooks/useResource';
import { dateRange, dayKey, formatClock, formatLongDate, searchKey, shiftDay } from '../lib/format';

const priority: DisplayState[] = ['CRITICAL', 'DROWSINESS_SIGNS', 'DISTRACTED', 'MONITORING_UNAVAILABLE', 'DISCONNECTED', 'UNCONFIRMED', 'NORMAL', 'OFFLINE'];
const byName = new Intl.Collator('vi');

export function Dashboard() {
  const { drivers, alerts, connection, lastSync, settings, retry } = useFeed();
  const { user } = useAuth();
  const alarm = useOutletContext<Alarm>();
  const now = useClock();
  const today = dayKey(now);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<DisplayState | ''>('');
  const query = searchKey(search);
  const filtered = Boolean(query || status);
  const loadHourly = useCallback((signal: AbortSignal) =>
    api.getHourly(dateRange(shiftDay(today, -6), today), signal), [today]);
  const hourly = useResource(loadHourly, Math.floor(now / 60_000));
  const entries = drivers.map((driver) => ({ driver, state: displayState(driver, connection, now, settings.heartbeatIntervalSec) }));
  const connected = entries.filter(({ state }) => !['OFFLINE', 'DISCONNECTED', 'UNCONFIRMED'].includes(state)).length;
  const critical = entries.filter(({ state }) => state === 'CRITICAL').length;
  const unavailable = entries.filter(({ state }) => ['DISCONNECTED', 'UNCONFIRMED', 'MONITORING_UNAVAILABLE'].includes(state)).length;
  const shown = entries.filter(({ driver, state }) =>
    (!status || state === status) && (!query || searchKey(`${driver.fullName} ${driver.vehicleName}`).includes(query)))
    .sort((a, b) => priority.indexOf(a.state) - priority.indexOf(b.state) || byName.compare(a.driver.fullName, b.driver.fullName));
  const current = connection === 'live';
  const clearFilters = () => { setSearch(''); setStatus(''); };
  return (
    <>
      <PageHeading title="Giám sát trực tiếp" description="Theo dõi trạng thái tài xế và xử lý cảnh báo theo thời gian thực."
        eyebrow={<><RadioTower size={14} aria-hidden /> {user ? `Ca trực của ${user.fullName}` : 'Tổng quan vận hành'}</>}
        actions={<span className="date-chip"><CalendarDays size={16} aria-hidden /> {formatLongDate(now)}</span>} />
      {connection === 'reconnecting' && <div className="connection-banner" role="status">
        <WifiOff size={20} aria-hidden /><span><strong>Đang kết nối lại…</strong> Trạng thái tài xế sẽ được xác nhận sau khi đồng bộ với máy chủ.</span>
        <button className="button button-secondary button-small" onClick={retry}>Kết nối lại</button>
      </div>}
      <div className="stats-grid dashboard-stats">
        <StatTile icon={BusFront} label="Tài xế theo dõi" value={lastSync ? drivers.length : '—'} description="Trong đội xe" />
        <StatTile icon={RadioTower} label="Đang trực tuyến" value={current ? connected : '—'} description="Có dữ liệu mới" />
        <StatTile icon={ShieldAlert} label="Nguy hiểm" value={current ? critical : '—'} description="Cần liên hệ ngay" tone="red" />
        <StatTile icon={WifiOff} label="Gián đoạn" value={current ? unavailable : '—'} description="Mất hoặc thiếu tín hiệu" tone="slate" />
      </div>
      <div className="dashboard-grid">
        <section className="card panel live-drivers" aria-labelledby="drivers-live-heading">
          <div className="section-heading live-section-heading">
            <div><h2 id="drivers-live-heading">Tài xế đang theo dõi {lastSync !== null && <span className="count-pill">{filtered ? `${shown.length}/${drivers.length}` : drivers.length}</span>}</h2>
              <p>{lastSync ? `Cập nhật lúc ${formatClock(lastSync)} · Giờ Việt Nam` : 'Đang đồng bộ trạng thái tài xế'}</p></div>
            <a className="alert-jump button button-secondary button-small" href="#recent-alerts"><Bell size={16} aria-hidden /> Cảnh báo <ChevronDown size={14} aria-hidden /></a>
          </div>
          <div className="live-toolbar">
            <SearchField value={search} onChange={setSearch} placeholder="Tìm tài xế, biển số xe…" />
            <label className="sr-only" htmlFor="live-status">Trạng thái tài xế</label>
            <select id="live-status" value={status} onChange={(event) => setStatus(event.target.value as DisplayState | '')}>
              <option value="">Mọi trạng thái</option>
              {priority.map((state) => <option key={state} value={state}>{statusLabel[state]}</option>)}
            </select>
          </div>
          {connection === 'connecting' && <div className="card"><Loading label="Đang kết nối giám sát…" /></div>}
          {connection === 'reconnecting' && !lastSync && <div className="card"><ErrorState message="Chưa đồng bộ được dữ liệu trực tiếp." retry={retry} /></div>}
          {lastSync && (shown.length
            ? <div className="driver-grid">{shown.map(({ driver, state }) => <DriverCard key={driver.driverId} driver={driver} state={state} />)}</div>
            : <Empty title={drivers.length ? 'Không tìm thấy tài xế phù hợp' : 'Chưa có tài xế để theo dõi'}
              description={drivers.length ? 'Thử đổi tên, biển số hoặc trạng thái.' : 'Tài xế của đội xe sẽ xuất hiện tại đây.'}
              action={filtered && <button type="button" className="button button-secondary button-small" onClick={clearFilters}>Xóa bộ lọc</button>} />)}
        </section>
        <aside className="card alerts-panel" id="recent-alerts" tabIndex={-1} aria-labelledby="alerts-heading">
          <div className="alerts-title"><span className="icon-tile tone-slate"><Bell size={19} aria-hidden /></span>
            <div><h2 id="alerts-heading">Cảnh báo gần đây</h2><p>Sự kiện trong 7 ngày gần nhất</p></div></div>
          <label className="audio-switch">
            {alarm.enabled ? <Volume2 size={17} aria-hidden /> : <VolumeX size={17} aria-hidden />}
            <span>Âm báo nguy hiểm</span>
            <input className="switch" type="checkbox" role="switch" checked={alarm.enabled} onChange={(event) => { void alarm.toggle(event.target.checked); }} />
          </label>
          {alarm.error && <p className="audio-error" role="alert">{alarm.error}</p>}
          {!current && lastSync && <p className="alerts-stale"><CircleAlert size={15} aria-hidden /> Hiển thị dữ liệu trước khi mất kết nối.</p>}
          {connection === 'connecting' && <Loading label="Đang tải cảnh báo…" />}
          {connection === 'reconnecting' && !lastSync && <ErrorState message="Chưa tải được cảnh báo." />}
          {lastSync && (alerts.length
            ? <ul className="alerts-list" aria-live="polite" aria-relevant="additions">{alerts.map((alert) => <AlertListItem key={alert.id} alert={alert} />)}</ul>
            : <Empty title="Chưa có cảnh báo gần đây" description="Cảnh báo mới sẽ xuất hiện tại đây." />)}
          <div className="alerts-footer"><BellRing size={16} aria-hidden /><TextLink to="/history">Xem lịch sử cảnh báo</TextLink></div>
        </aside>
        <section className="card panel hourly-panel" aria-label="Cảnh báo theo giờ">
          <SectionHeading title="Cảnh báo theo giờ" description="Phân bố cảnh báo theo giờ Việt Nam" actions={<span className="subtle-chip">7 ngày gần nhất</span>} />
          {hourly.loading && <Loading />}
          {hourly.error && <ErrorState message={hourly.error} retry={hourly.retry} />}
          {hourly.data && <HourlyAlertChart data={hourly.data} />}
        </section>
      </div>
    </>
  );
}
