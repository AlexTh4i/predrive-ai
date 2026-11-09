import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { AlertTriangle, BellRing, Check, Clock3, RadioTower, WifiOff, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useFeed } from '../hooks/useLiveFeed';
import { errorMessage } from '../hooks/useResource';
import { dayKey, dayOf, formatClock, formatDateTime, formatDayLabel } from '../lib/format';
import type { AlertEvent } from '../types';
import { eventLabels } from './ui';

export function Acknowledge({ alert, onSaved }: { alert: AlertEvent; onSaved?: (event: AlertEvent) => void }) {
  const { acknowledge } = useFeed();
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [confirmation, setConfirmation] = useState<AlertEvent>();
  const confirmed = alert.ackAt ? alert : confirmation;
  const button = useRef<HTMLButtonElement>(null);
  const result = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (editing || !restoreFocus.current) return;
    restoreFocus.current = false;
    (confirmed?.ackAt ? result.current : button.current)?.focus();
  }, [confirmed?.ackAt, editing]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError('');
    try {
      const updated = await acknowledge(alert.id, note);
      setConfirmation(updated);
      restoreFocus.current = true;
      setEditing(false);
      onSaved?.(updated);
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }
  if (confirmed?.ackAt) return (
    <div className="ack-done" ref={result} tabIndex={-1}>
      <span title={formatDateTime(confirmed.ackAt)}><Check size={14} aria-hidden /> Đã liên hệ</span>
      {confirmed.note && <p>{confirmed.note}</p>}
    </div>
  );
  return editing ? (
    <form className="ack-form" onSubmit={submit} aria-busy={saving}>
      <label>Ghi chú liên hệ <span className="muted">(tùy chọn)</span>
        <textarea autoFocus value={note} disabled={saving} onChange={(event) => setNote(event.target.value)}
          placeholder="Ví dụ đã gọi, tài xế sẽ dừng nghỉ." rows={2} maxLength={500} />
      </label>
      {error && <p role="alert" className="field-error">{error}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <button className="button button-primary button-small" type="submit" disabled={saving}>{saving ? 'Đang lưu…' : 'Lưu xác nhận'}</button>
        <button className="icon-button" type="button" aria-label="Hủy ghi nhận" disabled={saving} onClick={() => {
          restoreFocus.current = true;
          setEditing(false);
          setError('');
        }}>
          <X size={16} aria-hidden />
        </button>
      </div>
    </form>
  ) : <button className="ack-button" ref={button} onClick={() => setEditing(true)}><Check size={15} aria-hidden /> Đã liên hệ</button>;
}

export function AlertListItem({ alert }: { alert: AlertEvent }) {
  const critical = alert.level === 'CRITICAL';
  const day = dayOf(alert.capturedAt);
  const clock = formatClock(alert.capturedAt);
  const timeLabel = day === dayKey() ? clock : `${formatDayLabel(day)} · ${clock}`;
  const Icon = alert.type === 'DISCONNECTED' ? WifiOff : alert.type === 'LONG_DRIVING'
    ? Clock3 : critical ? BellRing : AlertTriangle;
  return (
    <li className={`alert-item ${critical ? 'alert-item-critical' : ''}`}>
      <span className={`icon-tile ${critical ? 'tone-red' : alert.type === 'DISCONNECTED' ? 'tone-slate' : 'tone-amber'}`}><Icon size={17} aria-hidden /></span>
      <div className="alert-body">
        <div className="alert-head">
          <strong>{eventLabels[alert.type]}</strong>
          <time dateTime={alert.capturedAt} title={formatDateTime(alert.capturedAt)}>{timeLabel}</time>
        </div>
        <p><Link to={`/drivers/${encodeURIComponent(alert.driverId)}`}>{alert.driverName}</Link><span className="alert-plate"> · {alert.vehicleName}</span></p>
        <span className={`severity ${critical ? 'tone-red' : 'tone-amber'}`}>
          {critical ? <RadioTower size={12} aria-hidden /> : <AlertTriangle size={12} aria-hidden />}
          {critical ? 'Nguy hiểm' : 'Cảnh báo'}
        </span>
        <Acknowledge alert={alert} />
      </div>
    </li>
  );
}
