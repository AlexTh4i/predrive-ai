import type { DateRange } from '../types';

export const TIME_ZONE = 'Asia/Ho_Chi_Minh';
const dayMs = 86_400_000;
const localDay = new Intl.DateTimeFormat('sv-SE', { timeZone: TIME_ZONE });
const localHour = new Intl.DateTimeFormat('vi-VN', {
  timeZone: TIME_ZONE, hour: '2-digit', hourCycle: 'h23',
});
const clock = new Intl.DateTimeFormat('vi-VN', {
  timeZone: TIME_ZONE, hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});
const dateTime = new Intl.DateTimeFormat('vi-VN', {
  timeZone: TIME_ZONE, dateStyle: 'short', timeStyle: 'short',
});
const longDate = new Intl.DateTimeFormat('vi-VN', {
  timeZone: TIME_ZONE, weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
});
const decimal = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat('vi-VN', { style: 'percent', maximumFractionDigits: 1 });

export const dayKey = (date: Date | number = Date.now()) => localDay.format(date);
export const shiftDay = (day: string, days: number) =>
  new Date(Date.parse(`${day}T00:00:00Z`) + days * dayMs).toISOString().slice(0, 10);
export const localDateTime = (day: string, time = '00:00:00') =>
  new Date(`${day}T${time}+07:00`).toISOString();
export const dayOf = (value: string) => dayKey(new Date(value));
export const hourOf = (value: string) =>
  Number(localHour.formatToParts(new Date(value)).find((part) => part.type === 'hour')?.value);
export const formatClock = (value: string | number) => clock.format(new Date(value));
export const formatDateTime = (value: string) => dateTime.format(new Date(value));
export function formatLongDate(value: number) {
  const label = longDate.format(value);
  return label.charAt(0).toUpperCase() + label.slice(1);
}
export const formatNumber = (value: number) => decimal.format(value);
export const formatRate = (value: number) => percent.format(value);
export const formatDayLabel = (day: string) => `${day.slice(8, 10)}/${day.slice(5, 7)}`;

export function dateRange(from?: string, to?: string): DateRange {
  return {
    from: from ? localDateTime(from) : undefined,
    to: to ? localDateTime(to, '23:59:59.999') : undefined,
  };
}

export function duration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} giờ ${String(minutes % 60).padStart(2, '0')} phút` : `${minutes} phút`;
}

export function normalizePhone(phone: string) {
  const clean = phone.replace(/[\s().-]/g, '');
  if (/^0\d{9}$/.test(clean)) return `+84${clean.slice(1)}`;
  if (/^\+?[1-9]\d{7,14}$/.test(clean)) return `+${clean.replace(/^\+/, '')}`;
  return null;
}

export function searchKey(value: string) {
  return value.toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '').replaceAll('đ', 'd').trim();
}
