import { useCallback, useState } from 'react';
import { ChevronLeft, ChevronRight, Clock3, Filter, History as HistoryIcon, RotateCcw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Acknowledge } from '../components/AlertListItem';
import { Empty, ErrorState, Loading, PageHeading, alertStatusLabel, eventLabels } from '../components/ui';
import { useResource } from '../hooks/useResource';
import { dateRange, dayOf, formatClock, formatDateTime, formatDayLabel } from '../lib/format';
import type { EventLevel, EventType } from '../types';

const emptyFilters = { driverId: '', from: '', to: '', level: '', type: '', acked: '' };
type Filters = typeof emptyFilters;
const pageSize = 10;
const getDrivers = (signal: AbortSignal) => api.getDrivers(signal);

export function History() {
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [page, setPage] = useState(1);
  const drivers = useResource(getDrivers);
  const invalid = Boolean(filters.from && filters.to && filters.from > filters.to);
  const activeFilters = Object.values(filters).filter(Boolean).length;
  const loadEvents = useCallback((signal: AbortSignal) => {
    if (invalid) return Promise.resolve({ items: [], total: 0 });
    return api.getEvents({
      driverId: filters.driverId || undefined,
      ...dateRange(filters.from, filters.to),
      level: (filters.level || undefined) as EventLevel | undefined,
      type: (filters.type || undefined) as EventType | undefined,
      acked: filters.acked ? filters.acked === 'yes' : undefined,
      page, pageSize,
    }, signal);
  }, [filters, invalid, page]);
  const events = useResource(loadEvents);
  const total = events.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  function change(key: keyof Filters, value: string) {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  }
  return (
    <>
      <PageHeading title="Lịch sử cảnh báo" description="Tra cứu sự kiện, kiểm tra trạng thái và ghi nhận liên hệ với tài xế."
        eyebrow={<><HistoryIcon size={14} aria-hidden /> NHẬT KÝ ĐỘI XE</>} />
      <section className="card panel filter-panel" aria-label="Bộ lọc cảnh báo">
        <div className="filter-heading">
          <span className="icon-tile tone-green"><Filter size={18} aria-hidden /></span>
          <h2>Bộ lọc {activeFilters > 0 && <span className="count-pill">{activeFilters}</span>}</h2>
          <button className="button button-secondary button-small" type="button" disabled={!activeFilters}
            onClick={() => { setFilters(emptyFilters); setPage(1); }}><RotateCcw size={14} aria-hidden /> Xóa bộ lọc</button>
        </div>
        <div className="history-filters">
          <label>Tài xế<select value={filters.driverId} disabled={drivers.loading} onChange={(event) => change('driverId', event.target.value)}>
            <option value="">Tất cả tài xế</option>{drivers.data?.map(({ id, fullName }) => <option key={id} value={id}>{fullName}</option>)}
          </select></label>
          <label>Từ ngày<input type="date" value={filters.from} max={filters.to || undefined} aria-invalid={invalid}
            aria-describedby={invalid ? 'date-range-error' : undefined} onChange={(event) => change('from', event.target.value)} /></label>
          <label>Đến ngày<input type="date" value={filters.to} min={filters.from || undefined} aria-invalid={invalid}
            aria-describedby={invalid ? 'date-range-error' : undefined} onChange={(event) => change('to', event.target.value)} /></label>
          <label>Mức độ<select value={filters.level} onChange={(event) => change('level', event.target.value)}>
            <option value="">Tất cả mức độ</option><option value="WARNING">Cảnh báo</option><option value="CRITICAL">Nguy hiểm</option>
          </select></label>
          <label>Loại sự kiện<select value={filters.type} onChange={(event) => change('type', event.target.value)}>
            <option value="">Tất cả sự kiện</option>{Object.entries(eventLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select></label>
          <label>Liên hệ<select value={filters.acked} onChange={(event) => change('acked', event.target.value)}>
            <option value="">Tất cả</option><option value="yes">Đã liên hệ</option><option value="no">Chưa liên hệ</option>
          </select></label>
        </div>
        {invalid && <p id="date-range-error" className="field-error" role="alert">Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.</p>}
        {drivers.error && <ErrorState message="Chưa tải được bộ lọc tài xế." retry={drivers.retry} />}
      </section>
      <section className="card data-panel" aria-labelledby="history-heading">
        <div className="data-panel-heading">
          <div><h2 id="history-heading">Nhật ký sự kiện</h2><p>Tất cả thời gian theo giờ Việt Nam (GMT+7)</p></div>
          {events.data && !invalid && <span className="count-pill">{total} sự kiện</span>}
        </div>
        {events.loading && !invalid && <Loading />}
        {events.error && !invalid && <ErrorState message={events.error} retry={events.retry} />}
        {events.data && !invalid && (events.data.items.length ? (
          <div className="table-scroll">
            <table className="data-table stack-table history-table" aria-labelledby="history-heading">
              <thead><tr><th scope="col">Thời gian</th><th scope="col">Tài xế / xe</th><th scope="col">Sự kiện</th><th scope="col">Mức độ</th><th scope="col">Liên hệ</th></tr></thead>
              <tbody>{events.data.items.map((event) => (
                <tr key={event.id}>
                  <td data-label="Thời gian"><time className="event-time" dateTime={event.capturedAt} title={formatDateTime(event.capturedAt)}>
                    <strong>{formatClock(event.capturedAt)}</strong> · {formatDayLabel(dayOf(event.capturedAt))}/{dayOf(event.capturedAt).slice(0, 4)}
                  </time>
                    {event.delayed && <span className="late-badge"><Clock3 size={12} aria-hidden /> Gửi muộn</span>}</td>
                  <td data-label="Tài xế"><Link className="table-link" to={`/drivers/${encodeURIComponent(event.driverId)}`}>{event.driverName}</Link><small>{event.vehicleName}</small></td>
                  <td data-label="Sự kiện"><strong>{eventLabels[event.type]}</strong><small>{alertStatusLabel[event.status]}</small></td>
                  <td data-label="Mức độ"><span className={`severity ${event.level === 'CRITICAL' ? 'tone-red' : 'tone-amber'}`}>
                    <span className="status-dot" aria-hidden />{event.level === 'CRITICAL' ? 'Nguy hiểm' : 'Cảnh báo'}</span></td>
                  <td data-label="Liên hệ" className="ack-cell"><Acknowledge alert={event} onSaved={() => {
                    if (filters.acked !== 'no') return;
                    if (page > 1 && events.data?.items.length === 1) setPage(page - 1);
                    else events.retry();
                  }} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty title="Không tìm thấy cảnh báo" description="Hãy thử thay đổi bộ lọc hoặc khoảng ngày."
          action={activeFilters > 0 && <button className="button button-secondary button-small" type="button"
            onClick={() => { setFilters(emptyFilters); setPage(1); }}>Bỏ tất cả bộ lọc</button>} />)}
        {events.data && total > 0 && !invalid && (
          <div className="pagination">
            <span>Trang <strong>{page} / {pages}</strong> · {total} sự kiện</span>
            <div className="flex gap-2">
              <button className="icon-button" onClick={() => setPage(page - 1)} disabled={page <= 1} aria-label="Trang trước"><ChevronLeft size={18} aria-hidden /></button>
              <button className="icon-button" onClick={() => setPage(page + 1)} disabled={page >= pages} aria-label="Trang sau"><ChevronRight size={18} aria-hidden /></button>
            </div>
          </div>
        )}
      </section>
    </>
  );
}
