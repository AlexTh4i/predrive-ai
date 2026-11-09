import { ArrowUpRight, BellRing, Clock3, Moon } from 'lucide-react';
import { memo } from 'react';
import { Link } from 'react-router-dom';
import type { DisplayState } from '../hooks/useLiveFeed';
import { duration } from '../lib/format';
import type { LiveDriverState } from '../types';
import { Avatar, StatusBadge, Vehicle } from './ui';

export const DriverCard = memo(function DriverCard({ driver, state }: { driver: LiveDriverState; state: DisplayState }) {
  return (
    <Link className={`driver-card card ${state === 'CRITICAL' ? 'driver-critical' : ''}`} to={`/drivers/${encodeURIComponent(driver.driverId)}`}>
      <div className="driver-card-top">
        <Avatar name={driver.fullName} id={driver.driverId} />
        {state === 'CRITICAL' && <span className="driver-bell"><BellRing size={13} aria-hidden /></span>}
        <div className="driver-identity"><h3>{driver.fullName}</h3><Vehicle name={driver.vehicleName} /></div>
        <span className="driver-arrow"><ArrowUpRight size={16} aria-hidden /></span>
      </div>
      <StatusBadge state={state} />
      <dl className="driver-metrics">
        <div><dt><Clock3 size={14} aria-hidden /> Lái liên tục</dt><dd>{state === 'UNCONFIRMED' ? '—' : duration(driver.continuousDrivingSec)}</dd></div>
        <div><dt><Moon size={14} aria-hidden /> Buồn ngủ hôm nay</dt><dd>{state === 'UNCONFIRMED' ? '—' : `${driver.drowsyCountToday} lần`}</dd></div>
      </dl>
    </Link>
  );
});
