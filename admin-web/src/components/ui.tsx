import { AlertCircle, ArrowRight, BellRing, BusFront, CircleHelp, EyeOff, LoaderCircle, MessageCircle, Moon, Phone, Power, Search, WifiOff } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { DisplayState } from '../hooks/useLiveFeed';
import { normalizePhone } from '../lib/format';
import type { AlertEvent, EventType } from '../types';
import { ParrotMascot } from './ParrotMascot';

export const statusLabel: Record<DisplayState, string> = {
  NORMAL: 'Bình thường',
  DROWSINESS_SIGNS: 'Lim dim',
  CRITICAL: 'Nguy hiểm',
  DISTRACTED: 'Mất tập trung',
  MONITORING_UNAVAILABLE: 'Gián đoạn giám sát',
  DISCONNECTED: 'Mất kết nối',
  OFFLINE: 'Ngoại tuyến',
  UNCONFIRMED: 'Chưa xác nhận',
};

export const eventLabels: Record<EventType, string> = {
  DROWSINESS: 'Buồn ngủ',
  LONG_DRIVING: 'Lái quá lâu',
  DISCONNECTED: 'Mất kết nối',
  REST_CLAIM_REJECTED: 'Không ghi nhận nghỉ',
};

export const alertStatusLabel: Record<AlertEvent['status'], string> = {
  OPEN: 'Đang mở', ESCALATED: 'Đã nâng mức', CLOSED: 'Đã đóng',
};

const statusIcons: Partial<Record<DisplayState, LucideIcon>> = {
  CRITICAL: BellRing, DROWSINESS_SIGNS: Moon, OFFLINE: Power, DISCONNECTED: WifiOff,
  UNCONFIRMED: CircleHelp, MONITORING_UNAVAILABLE: EyeOff,
};

export function StatusBadge({ state }: { state: DisplayState }) {
  const Icon = statusIcons[state];
  return (
    <span className={`status-badge status-${state.toLowerCase()}`}>
      {Icon ? <Icon size={13} aria-hidden /> : <span className="status-dot" aria-hidden />}
      {statusLabel[state]}
    </span>
  );
}

export function Avatar({ name, id, avatarUrl, className = '' }: {
  name: string; id: string; avatarUrl?: string | null; className?: string;
}) {
  const [first, last] = name.trim().split(/\s+/).filter(Boolean).slice(-2);
  const initials = `${first?.[0] ?? ''}${last?.[0] ?? ''}`.toUpperCase();
  const tone = [...id].reduce((total, char) => total + char.charCodeAt(0), 0) % 6;
  return (
    <span className={`avatar avatar-${tone} ${className}`} aria-hidden>
      {initials}
      {avatarUrl && <img src={avatarUrl} alt="" referrerPolicy="no-referrer" onError={(event) => { event.currentTarget.hidden = true; }} />}
    </span>
  );
}

export function Vehicle({ name }: { name: string }) {
  return <span className="vehicle-label"><BusFront size={14} aria-hidden /> {name}</span>;
}

export function PageHeading({ title, description, eyebrow, actions }: {
  title: string; description: string; eyebrow?: ReactNode; actions?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function SectionHeading({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="section-heading">
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      {actions}
    </div>
  );
}

export function Loading({ label = 'Đang tải dữ liệu…' }: { label?: string }) {
  return <div className="feedback" role="status"><LoaderCircle className="spin" size={21} aria-hidden />{label}</div>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="feedback feedback-error" role="alert">
      <AlertCircle size={21} aria-hidden />
      <span>{message}</span>
      {retry && <button className="button button-secondary button-small" onClick={retry}>Thử lại</button>}
    </div>
  );
}

export function Empty({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <span className="empty-mascot"><ParrotMascot mood="peek" /></span>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}

export function SearchField({ value, onChange, placeholder }: { value: string; onChange(value: string): void; placeholder: string }) {
  return (
    <label className="search-field">
      <Search size={17} aria-hidden />
      <span className="sr-only">{placeholder}</span>
      <input type="search" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}

export function ContactLinks({ phone }: { phone: string }) {
  const normalized = normalizePhone(phone);
  if (!normalized) return <p className="muted">Chưa có số điện thoại hợp lệ.</p>;
  return (
    <div className="profile-contact">
      <a className="button button-primary" href={`tel:${normalized}`}><Phone size={17} aria-hidden /> Gọi</a>
      <a className="button button-secondary" href={`https://zalo.me/${normalized.slice(1)}`} target="_blank" rel="noreferrer">
        <MessageCircle size={17} aria-hidden /> Nhắn Zalo
      </a>
    </div>
  );
}

export function TextLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link className="text-link" to={to}>{children}<ArrowRight size={15} aria-hidden /></Link>;
}
