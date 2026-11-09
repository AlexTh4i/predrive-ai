import { ChevronDown } from 'lucide-react';
import { memo } from 'react';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { formatNumber } from '../lib/format';
import type { HourlyStats } from '../types';
import { Empty } from './ui';

const hourLabel = (hour: number) => `${String(hour).padStart(2, '0')}:00`;
const axis = { fill: 'var(--muted)', fontSize: 11 };
const tooltipStyle = { borderRadius: 12, borderColor: 'var(--control-border)', fontSize: 12, boxShadow: 'var(--shadow-float)' };
const tooltipLabel = { color: 'var(--text)', fontWeight: 700, marginBottom: 4 };
const countLabel = (value: unknown) => formatNumber(Number(value));

export const HourlyAlertChart = memo(function HourlyAlertChart({ data, simple = false }: { data: HourlyStats[]; simple?: boolean }) {
  const hourly = Array.from({ length: 24 }, (_, hour) => data.find((item) => item.hour === hour) ?? { hour, warning: 0, critical: 0 });
  const warningCount = hourly.reduce((sum, item) => sum + item.warning, 0);
  const criticalCount = hourly.reduce((sum, item) => sum + item.critical, 0);
  if (warningCount + criticalCount === 0) {
    return <Empty title="Chưa có cảnh báo trong khoảng này" description="Biểu đồ sẽ cập nhật khi có dữ liệu." />;
  }
  return (
    <>
      <div className="chart-legend">
        <span><i className={simple ? 'chart-total' : 'chart-warning'} /> {simple ? 'Tổng cảnh báo' : 'Cảnh báo'} <strong>{formatNumber(warningCount)}</strong></span>
        {!simple && <span><i className="chart-critical" /> Nguy hiểm <strong>{formatNumber(criticalCount)}</strong></span>}
      </div>
      <div className="chart-frame" aria-label="Biểu đồ cảnh báo theo giờ Việt Nam">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
          <BarChart data={hourly} margin={{ top: 10, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 4" />
            <XAxis dataKey="hour" tickFormatter={hourLabel} tick={axis} interval="preserveStartEnd" minTickGap={14} tickMargin={9} axisLine={false} tickLine={false} />
            <YAxis tick={axis} width={36} tickLine={false} axisLine={false} allowDecimals={false} tickFormatter={countLabel} />
            <Tooltip labelFormatter={(hour) => `${hourLabel(Number(hour))} · Giờ Việt Nam`} formatter={countLabel}
              labelStyle={tooltipLabel} contentStyle={tooltipStyle} itemStyle={{ color: 'var(--text)' }} cursor={{ fill: 'var(--surface-subtle)' }} />
            <Bar dataKey="warning" name={simple ? 'Tổng cảnh báo' : 'Cảnh báo'} stackId="hour" fill={simple ? 'var(--brand-ink)' : 'var(--amber)'}
              maxBarSize={26} radius={simple ? [4, 4, 0, 0] : undefined} isAnimationActive={false} />
            {!simple && <Bar dataKey="critical" name="Nguy hiểm" stackId="hour" fill="var(--red)" maxBarSize={26} radius={[4, 4, 0, 0]} isAnimationActive={false} />}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <details className="chart-details">
        <summary>Xem số liệu theo giờ <ChevronDown size={15} aria-hidden /></summary>
        <div className="hour-values">{hourly.map(({ hour, warning, critical }) => (
          <span key={hour}><strong>{hourLabel(hour)}</strong> {formatNumber(warning + critical)}{!simple && ` (${formatNumber(critical)} nguy hiểm)`}</span>
        ))}</div>
      </details>
    </>
  );
});

export const TrendChart = memo(function TrendChart({ data }: { data: { label: string; count: number }[] }) {
  if (!data.some((item) => item.count)) return <Empty title="Chưa có cảnh báo để hiển thị xu hướng" />;
  return (
    <>
      <div className="chart-legend"><span><i className="chart-total" /> Tổng cảnh báo <strong>{formatNumber(data.reduce((sum, item) => sum + item.count, 0))}</strong></span></div>
      <div className="chart-frame" aria-label="Biểu đồ xu hướng cảnh báo">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
          <LineChart data={data} margin={{ top: 12, right: 18, bottom: 4, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 4" />
            <XAxis dataKey="label" tick={axis} tickLine={false} axisLine={false} minTickGap={14} tickMargin={9} />
            <YAxis tick={axis} width={36} tickLine={false} axisLine={false} allowDecimals={false} tickFormatter={countLabel} />
            <Tooltip formatter={countLabel} labelStyle={tooltipLabel} contentStyle={tooltipStyle} itemStyle={{ color: 'var(--text)' }} />
            <Line type="monotone" dataKey="count" name="Cảnh báo" stroke="var(--brand-ink)" strokeWidth={3}
              dot={{ r: 4, fill: 'var(--surface)', strokeWidth: 2 }} activeDot={{ r: 5 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details className="chart-details"><summary>Xem số liệu xu hướng <ChevronDown size={15} aria-hidden /></summary>
        <div className="hour-values">{data.map(({ label, count }) => <span key={label}><strong>{label}</strong> {formatNumber(count)}</span>)}</div>
      </details>
    </>
  );
});
