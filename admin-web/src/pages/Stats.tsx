import { useCallback, useMemo, useState } from 'react';
import { BarChart3, CalendarDays, EyeOff, Moon, WifiOff } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { HourlyAlertChart, TrendChart } from '../components/Charts';
import { StatTile } from '../components/StatTile';
import { Avatar, Empty, ErrorState, Loading, PageHeading, SectionHeading } from '../components/ui';
import { useClock } from '../hooks/useClock';
import { useResource } from '../hooks/useResource';
import { dateRange, dayKey, formatDayLabel, formatNumber, formatRate, shiftDay } from '../lib/format';

export function Stats() {
  const today = dayKey(useClock());
  const [group, setGroup] = useState<'day' | 'week'>('day');
  const start = shiftDay(today, group === 'day' ? -6 : -27);
  const range = useMemo(() => dateRange(start, today), [start, today]);
  const hourly = useResource(useCallback((signal) => api.getHourly(range, signal), [range]));
  const health = useResource(useCallback((signal) => api.getSystemHealth(range, signal), [range]));
  const rankingResult = useResource(useCallback((signal) => api.getRanking(range, signal), [range]));
  const loadTrend = useCallback((signal: AbortSignal) => {
    const periods = group === 'day' ? 7 : 4;
    const length = group === 'day' ? 1 : 7;
    return Promise.all(Array.from({ length: periods }, async (_, index) => {
      const to = shiftDay(today, -(periods - 1 - index) * length);
      const from = shiftDay(to, 1 - length);
      const { total } = await api.getEvents({ ...dateRange(from, to), page: 1, pageSize: 1 }, signal);
      return { label: group === 'day' ? formatDayLabel(from) : `${formatDayLabel(from)}–${formatDayLabel(to)}`, count: total };
    }));
  }, [today, group]);
  const trend = useResource(loadTrend);
  const ranking = useMemo(() => rankingResult.data?.slice().sort((a, b) =>
    b.alertsPerDrivingHour - a.alertsPerDrivingHour || b.alertCount - a.alertCount), [rankingResult.data]);
  return (
    <>
      <PageHeading title="Thống kê" description="Xem phân bố cảnh báo, xu hướng và tình trạng giám sát của đội xe."
        eyebrow={<><BarChart3 size={14} aria-hidden /> BÁO CÁO ĐỘI XE</>}
        actions={<div className="stats-period"><span className="date-chip"><CalendarDays size={15} aria-hidden />
          {formatDayLabel(start)} – {formatDayLabel(today)}</span><div className="segmented" role="group" aria-label="Khoảng thời gian">
          <button type="button" aria-pressed={group === 'day'} onClick={() => setGroup('day')}>7 ngày</button>
          <button type="button" aria-pressed={group === 'week'} onClick={() => setGroup('week')}>4 tuần</button>
        </div></div>} />
      <section aria-label="Sức khỏe hệ thống" className="page-section">
        <SectionHeading title="Sức khỏe hệ thống" description="Tín hiệu chất lượng giám sát trong khoảng đã chọn" />
        {health.loading && <div className="card"><Loading /></div>}
        {health.error && <div className="card"><ErrorState message={health.error} retry={health.retry} /></div>}
        {health.data && <div className="stats-grid">
          <StatTile icon={Moon} label="Tỷ lệ quá tối" value={formatRate(health.data.tooDarkRate)} description="Điều kiện ánh sáng" tone="amber" />
          <StatTile icon={EyeOff} label="Tỷ lệ gián đoạn giám sát" value={formatRate(health.data.unavailableRate)} description="Khả năng giám sát" tone="slate" />
          <StatTile icon={WifiOff} label="Sự kiện mất kết nối" value={formatNumber(health.data.disconnectedCount)} description="Tổng số sự kiện" tone="red" />
        </div>}
      </section>
      <div className="report-grid page-section">
        <section className="card panel" aria-label="Cảnh báo theo giờ">
          <SectionHeading title="Cảnh báo theo giờ" description="Giờ Việt Nam (GMT+7)" />
          {hourly.loading && <Loading />}
          {hourly.error && <ErrorState message={hourly.error} retry={hourly.retry} />}
          {hourly.data && <HourlyAlertChart data={hourly.data} />}
        </section>
        <section className="card panel" aria-label="Xu hướng cảnh báo">
          <SectionHeading title="Xu hướng cảnh báo" description={group === 'day' ? 'Số sự kiện theo ngày' : 'Số sự kiện theo nhóm 7 ngày'} />
          {trend.loading && <Loading />}
          {trend.error && <ErrorState message={trend.error} retry={trend.retry} />}
          {trend.data && <TrendChart data={trend.data} />}
        </section>
      </div>
      <section className="card data-panel" aria-labelledby="ranking-heading">
        <div className="data-panel-heading"><div><h2 id="ranking-heading">Xếp hạng tài xế</h2><p>Sắp xếp theo số cảnh báo trên mỗi giờ lái</p></div></div>
        {rankingResult.loading && <Loading />}
        {rankingResult.error && <ErrorState message={rankingResult.error} retry={rankingResult.retry} />}
        {ranking && (ranking.length ? <div className="table-scroll">
          <table className="data-table stack-table" aria-labelledby="ranking-heading">
            <thead><tr><th scope="col">Hạng</th><th scope="col">Tài xế</th><th scope="col">Cảnh báo / giờ lái</th><th scope="col">Tổng cảnh báo</th></tr></thead>
            <tbody>{ranking.map((driver, i) => <tr key={driver.driverId}>
              <td data-label="Hạng"><span className="rank-badge">{String(i + 1).padStart(2, '0')}</span></td>
              <td data-label="Tài xế"><Link className="table-link ranking-driver" to={`/drivers/${encodeURIComponent(driver.driverId)}`}>
                <Avatar name={driver.fullName} id={driver.driverId} /> {driver.fullName}
              </Link></td>
              <td data-label="Cảnh báo / giờ lái"><strong>{formatNumber(driver.alertsPerDrivingHour)}</strong></td>
              <td data-label="Tổng cảnh báo">{formatNumber(driver.alertCount)}</td>
            </tr>)}</tbody>
          </table>
        </div> : <Empty title="Chưa có dữ liệu xếp hạng" description="Xếp hạng sẽ xuất hiện khi có dữ liệu lái xe." />)}
      </section>
    </>
  );
}
