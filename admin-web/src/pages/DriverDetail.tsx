import { useCallback, useMemo } from 'react';
import { Activity, ArrowLeft, BellRing, Clock3, Gauge, Phone } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import { HourlyAlertChart } from '../components/Charts';
import { StatTile } from '../components/StatTile';
import { Avatar, ContactLinks, Empty, ErrorState, Loading, SectionHeading, StatusBadge, Vehicle } from '../components/ui';
import { useClock } from '../hooks/useClock';
import { displayState, useFeed } from '../hooks/useLiveFeed';
import { useResource } from '../hooks/useResource';
import { dateRange, dayKey, duration, formatDateTime, formatNumber, shiftDay } from '../lib/format';

export function DriverDetail() {
  const { id = '' } = useParams();
  const { drivers, connection, settings } = useFeed();
  const now = useClock();
  const today = dayKey(now);
  const load = useCallback((signal: AbortSignal) => api.getDriver(id, signal), [id]);
  const loadStats = useCallback((signal: AbortSignal) => api.getDriverStats(id, dateRange(shiftDay(today, -6), today), signal), [id, today]);
  const profile = useResource(load);
  const stats = useResource(loadStats);
  const chartData = useMemo(() => stats.data?.hourly.map(({ hour, count }) => ({ hour, warning: count, critical: 0 })) ?? [], [stats.data]);
  const driver = profile.data;
  const live = drivers.find((entry) => entry.driverId === id);
  return (
    <>
      <Link to="/drivers" className="text-link back-link"><ArrowLeft size={16} aria-hidden /> Danh sách tài xế</Link>
      {profile.loading && <div className="card"><Loading label="Đang tải hồ sơ tài xế…" /></div>}
      {profile.error && <div className="card"><ErrorState message={profile.error} retry={profile.retry} /></div>}
      {driver && <>
        <header className="card profile-header">
          <Avatar name={driver.fullName} id={driver.id} avatarUrl={driver.avatarUrl} />
          <div className="profile-identity">
            <div className="eyebrow"><Activity size={13} aria-hidden /> HỒ SƠ TÀI XẾ</div>
            <h1>{driver.fullName}</h1>
            <div className="profile-meta"><Vehicle name={driver.vehicleName} />
              {driver.phone && <span className="profile-phone"><Phone size={14} aria-hidden />{driver.phone}</span>}
              <StatusBadge state={live ? displayState(live, connection, now, settings.heartbeatIntervalSec) : 'UNCONFIRMED'} /></div>
          </div>
          <ContactLinks phone={driver.phone} />
        </header>
        {stats.loading && <div className="card page-section"><Loading label="Đang tải thống kê tài xế…" /></div>}
        {stats.error && <div className="card page-section"><ErrorState message={stats.error} retry={stats.retry} /></div>}
        {stats.data && <>
          <div className="stats-grid">
            <StatTile icon={Clock3} label="Tổng thời gian lái" value={duration(stats.data.totalDrivingSec)} description="7 ngày gần nhất" />
            <StatTile icon={BellRing} label="Số cảnh báo" value={stats.data.alertCount} description="7 ngày gần nhất" tone="amber" />
            <StatTile icon={Gauge} label="Cảnh báo mỗi giờ lái" value={formatNumber(stats.data.alertsPerDrivingHour)} description="7 ngày gần nhất" tone="slate" />
          </div>
          <section className="card panel page-section" aria-label="Cảnh báo theo giờ của tài xế">
            <SectionHeading title="Cảnh báo theo giờ" description="Phân bố trong 7 ngày gần nhất · Giờ Việt Nam" />
            <HourlyAlertChart simple data={chartData} />
          </section>
        </>}
        <section className="card data-panel" aria-labelledby="sessions-heading">
          <div className="data-panel-heading"><div><h2 id="sessions-heading">Phiên giám sát gần đây</h2><p>Thời gian hiển thị theo giờ Việt Nam</p></div></div>
          {driver.recentSessions.length ? <div className="table-scroll">
            <table className="data-table stack-table" aria-labelledby="sessions-heading">
              <thead><tr><th scope="col">Bắt đầu</th><th scope="col">Kết thúc</th><th scope="col">Thời gian lái</th><th scope="col">Cảnh báo</th><th scope="col">Nguy hiểm</th></tr></thead>
              <tbody>{driver.recentSessions.map((session) => <tr key={session.id}>
                <td data-label="Bắt đầu"><time dateTime={session.startedAt}>{formatDateTime(session.startedAt)}</time></td>
                <td data-label="Kết thúc">{session.endedAt ? <time dateTime={session.endedAt}>{formatDateTime(session.endedAt)}</time> : 'Đang mở'}</td>
                <td data-label="Thời gian lái">{duration(session.totalDrivingSec)}</td>
                <td data-label="Cảnh báo">{session.warningCount}</td><td data-label="Nguy hiểm">{session.criticalCount}</td>
              </tr>)}</tbody>
            </table>
          </div> : <Empty title="Chưa có phiên giám sát" />}
        </section>
      </>}
    </>
  );
}
