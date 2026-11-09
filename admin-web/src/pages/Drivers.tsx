import { useMemo, useState } from 'react';
import { ArrowUpRight, Phone, UsersRound } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Avatar, Empty, ErrorState, Loading, PageHeading, SearchField, StatusBadge, Vehicle } from '../components/ui';
import { useClock } from '../hooks/useClock';
import { displayState, useFeed } from '../hooks/useLiveFeed';
import { useResource } from '../hooks/useResource';
import { searchKey } from '../lib/format';

const getDrivers = (signal: AbortSignal) => api.getDrivers(signal);

export function Drivers() {
  const result = useResource(getDrivers);
  const { drivers: live, connection, settings } = useFeed();
  const now = useClock();
  const [search, setSearch] = useState('');
  const query = searchKey(search);
  const drivers = useMemo(() => result.data?.filter((driver) =>
    !query || searchKey(`${driver.fullName} ${driver.vehicleName} ${driver.phone}`).includes(query)), [query, result.data]);
  const liveById = useMemo(() => new Map(live.map((driver) => [driver.driverId, driver])), [live]);
  return (
    <>
      <PageHeading title="Danh sách tài xế" description="Xem hồ sơ tài xế, xe được phân công và trạng thái giám sát."
        eyebrow={<><UsersRound size={14} aria-hidden /> ĐỘI XE</>} />
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
