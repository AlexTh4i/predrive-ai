import { useState } from 'react';
import type { FormEvent } from 'react';
import { AlertCircle, Archive, Check, Clock3, Info, LoaderCircle, MapPin, Save, Settings2 } from 'lucide-react';
import { api } from '../api';
import { ErrorState, Loading, PageHeading, SectionHeading } from '../components/ui';
import { useFeed } from '../hooks/useLiveFeed';
import { errorMessage, useResource } from '../hooks/useResource';
import type { Settings as SettingsData } from '../types';

const loadSettings = (signal: AbortSignal) => api.getSettings(signal);

function fields(settings: SettingsData) {
  return {
    warning: String(settings.continuousWarnSec / 60),
    critical: String(settings.continuousCriticalSec / 60),
    rest: String(settings.restResetMin),
    shareLocation: settings.shareLocation,
    level1Sec: String(settings.level1Sec ?? 1),
    level2Sec: String(settings.level2Sec ?? 2),
    level3Sec: String(settings.level3Sec ?? 4),
    hbRetention: String(settings.heartbeatRetentionDays ?? 30),
    locRetention: String(settings.locationRetentionDays ?? 90),
    evRetention: String(settings.eventRetentionDays ?? 365),
    auditRetention: String(settings.auditRetentionDays ?? 730),
  };
}

function SettingsForm({ initial }: { initial: SettingsData }) {
  const { applySettings } = useFeed();
  const [saved, setSaved] = useState(initial);
  const [draft, setDraft] = useState(() => fields(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [validation, setValidation] = useState<{ field: 'warning' | 'critical' | 'rest'; message: string }>();
  const [success, setSuccess] = useState(false);
  const baseSaved = fields(saved);
  const dirty = JSON.stringify(baseSaved) !== JSON.stringify(draft);

  function update<K extends keyof typeof draft>(key: K, value: typeof draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    setError('');
    setValidation(undefined);
    setSuccess(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !dirty) return;
    const warning = Math.round(Number(draft.warning) * 60);
    const critical = Math.round(Number(draft.critical) * 60);
    const rest = Number(draft.rest);
    const hbRet = Math.max(1, Math.round(Number(draft.hbRetention) || 30));
    const locRet = Math.max(1, Math.round(Number(draft.locRetention) || 90));
    const evRet = Math.max(1, Math.round(Number(draft.evRetention) || 365));
    const auditRet = Math.max(1, Math.round(Number(draft.auditRetention) || 730));
    const lvl1 = Number(draft.level1Sec) || 1;
    const lvl2 = Number(draft.level2Sec) || 2;
    const lvl3 = Number(draft.level3Sec) || 4;

    const issue = [
      { field: 'warning', message: 'Nhập ngưỡng cảnh báo dương có thể quy đổi sang giây.', invalid: !Number.isSafeInteger(warning) || warning < 1 },
      { field: 'critical', message: 'Nhập ngưỡng nguy hiểm dương có thể quy đổi sang giây.', invalid: !Number.isSafeInteger(critical) || critical < 1 },
      { field: 'rest', message: 'Số phút nghỉ phải là số nguyên dương.', invalid: !Number.isSafeInteger(rest) || rest < 1 },
      { field: 'critical', message: 'Ngưỡng nguy hiểm phải lớn hơn ngưỡng cảnh báo.', invalid: warning >= critical },
    ] as const;
    const invalid = issue.find((item) => item.invalid);
    if (invalid) {
      setValidation(invalid);
      event.currentTarget.querySelector<HTMLInputElement>(`#threshold-${invalid.field}`)?.focus();
      return;
    }
    setError('');
    setValidation(undefined);
    setSuccess(false);
    setSaving(true);

    const retentionModified =
      draft.hbRetention !== baseSaved.hbRetention ||
      draft.locRetention !== baseSaved.locRetention ||
      draft.evRetention !== baseSaved.evRetention ||
      draft.auditRetention !== baseSaved.auditRetention;
    const includeRetention = saved.heartbeatRetentionDays !== undefined || retentionModified;

    const levelsModified =
      draft.level1Sec !== baseSaved.level1Sec ||
      draft.level2Sec !== baseSaved.level2Sec ||
      draft.level3Sec !== baseSaved.level3Sec;
    const includeLevels = saved.level1Sec !== undefined || levelsModified;

    const payload: SettingsData = {
      ...saved,
      continuousWarnSec: warning,
      continuousCriticalSec: critical,
      restResetMin: rest,
      shareLocation: draft.shareLocation,
      ...(includeLevels
        ? {
            level1Sec: lvl1,
            level2Sec: lvl2,
            level3Sec: lvl3,
          }
        : {}),
      ...(includeRetention
        ? {
            heartbeatRetentionDays: hbRet,
            locationRetentionDays: locRet,
            eventRetentionDays: evRet,
            auditRetentionDays: auditRet,
          }
        : {}),
    };

    try {
      const updated = await api.updateSettings(payload);
      setSaved(updated);
      setDraft(fields(updated));
      applySettings(updated);
      setSuccess(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }
  return (
    <form className="settings-form" onSubmit={submit} aria-busy={saving}>
      <fieldset disabled={saving} className="card panel settings-panel" aria-label="Ngưỡng lái liên tục">
        <SectionHeading title="Ngưỡng lái liên tục" description="Thiết lập thời gian trước khi hệ thống phát cảnh báo."
          actions={<span className="icon-tile tone-amber"><Clock3 size={20} aria-hidden /></span>} />
        <div className="settings-fields">
          <div><label htmlFor="threshold-warning">Ngưỡng cảnh báo (phút)</label>
            <input id="threshold-warning" type="number" min={1 / 60} step="any" required value={draft.warning}
              aria-invalid={validation?.field === 'warning'} aria-describedby={validation?.field === 'warning' ? 'threshold-error' : undefined}
              onChange={(event) => update('warning', event.target.value)} /></div>
          <div><label htmlFor="threshold-critical">Ngưỡng nguy hiểm (phút)</label>
            <input id="threshold-critical" type="number" min={1 / 60} step="any" required value={draft.critical}
              aria-invalid={validation?.field === 'critical'} aria-describedby={validation?.field === 'critical' ? 'threshold-error' : undefined}
              onChange={(event) => update('critical', event.target.value)} /></div>
          <div><label htmlFor="threshold-rest">Số phút nghỉ để đặt lại</label>
            <input id="threshold-rest" type="number" min={1} step={1} required value={draft.rest}
              aria-invalid={validation?.field === 'rest'} aria-describedby={validation?.field === 'rest' ? 'threshold-error' : undefined}
              onChange={(event) => update('rest', event.target.value)} /></div>
        </div>
        {validation && <p id="threshold-error" role="alert" className="settings-validation field-error">
          <AlertCircle size={16} aria-hidden />{validation.message}
        </p>}
        <p className="settings-hint"><Info size={16} aria-hidden /> Chu kỳ heartbeat của thiết bị hiện là {saved.heartbeatIntervalSec} giây.</p>
      </fieldset>
      <fieldset disabled={saving} className="card panel settings-panel" aria-label="Cảnh báo buồn ngủ 3 mức">
        <SectionHeading title="Cảnh báo buồn ngủ 3 mức" description="Thời gian nhắm mắt để phát: Mức 1 nhắc nhẹ → Mức 2 chuông cabin → Mức 3 báo điều hành (áp dụng trực tiếp cho app không cần build lại)."
          actions={<span className="icon-tile tone-amber"><AlertCircle size={19} aria-hidden /></span>} />
        <div className="settings-fields">
          <div><label htmlFor="lvl-1">Mức 1 — Nhắc nhẹ (giây)</label>
            <input id="lvl-1" type="number" min={0.2} max={30} step="any" required value={draft.level1Sec}
              onChange={(event) => update('level1Sec', event.target.value)} /></div>
          <div><label htmlFor="lvl-2">Mức 2 — Chuông cabin (giây)</label>
            <input id="lvl-2" type="number" min={0.5} max={60} step="any" required value={draft.level2Sec}
              onChange={(event) => update('level2Sec', event.target.value)} /></div>
          <div><label htmlFor="lvl-3">Mức 3 — Báo điều hành (giây)</label>
            <input id="lvl-3" type="number" min={1} max={120} step="any" required value={draft.level3Sec}
              onChange={(event) => update('level3Sec', event.target.value)} /></div>
        </div>
      </fieldset>
      <fieldset disabled={saving} className="card panel settings-panel" aria-label="Chia sẻ vị trí">
        <SectionHeading title="Chia sẻ vị trí" description="Cấu hình cho phép app tài xế gửi vị trí trong phiên giám sát."
          actions={<span className="icon-tile tone-green"><MapPin size={19} aria-hidden /></span>} />
        <label className="settings-switch">
          <span><strong>Cho phép chia sẻ vị trí</strong><small>Áp dụng cho các thiết bị của đội xe.</small></span>
          <input className="switch" type="checkbox" role="switch" checked={draft.shareLocation}
            aria-label="Cho phép chia sẻ vị trí" onChange={(event) => update('shareLocation', event.target.checked)} />
        </label>
      </fieldset>
      <fieldset disabled={saving} className="card panel settings-panel" aria-label="Thời hạn lưu trữ dữ liệu">
        <SectionHeading title="Thời hạn lưu trữ dữ liệu (Retention)" description="Số ngày giữ dữ liệu trước khi tác vụ dọn dẹp hằng ngày tự động xóa."
          actions={<span className="icon-tile tone-amber"><Archive size={19} aria-hidden /></span>} />
        <div className="settings-fields">
          <div><label htmlFor="ret-heartbeat">Heartbeat (ngày)</label>
            <input id="ret-heartbeat" type="number" min={1} max={3650} step={1} required value={draft.hbRetention}
              onChange={(event) => update('hbRetention', event.target.value)} /></div>
          <div><label htmlFor="ret-location">Vị trí GPS (ngày)</label>
            <input id="ret-location" type="number" min={1} max={3650} step={1} required value={draft.locRetention}
              onChange={(event) => update('locRetention', event.target.value)} /></div>
          <div><label htmlFor="ret-event">Sự kiện đã đóng (ngày)</label>
            <input id="ret-event" type="number" min={1} max={3650} step={1} required value={draft.evRetention}
              onChange={(event) => update('evRetention', event.target.value)} /></div>
          <div><label htmlFor="ret-audit">Nhật ký Audit (ngày)</label>
            <input id="ret-audit" type="number" min={1} max={3650} step={1} required value={draft.auditRetention}
              onChange={(event) => update('auditRetention', event.target.value)} /></div>
        </div>
      </fieldset>
      {error && <div className="card"><ErrorState message={`Chưa lưu được cài đặt. ${error}`} /></div>}
      <div className="card settings-save">
        <p role="status" className={`settings-status ${dirty ? 'settings-dirty' : ''}`}>
          {saving ? <LoaderCircle size={17} className="spin" aria-hidden /> : dirty ? <AlertCircle size={17} aria-hidden /> : <Check size={17} aria-hidden />}
          {saving ? 'Đang lưu cài đặt…' : dirty ? 'Có thay đổi chưa lưu' : success ? 'Đã lưu cài đặt.' : 'Cài đặt đã đồng bộ'}
        </p>
        <div className="settings-actions">
          <button type="button" className="button button-secondary" disabled={saving || !dirty} onClick={() => {
            setDraft(fields(saved)); setError(''); setValidation(undefined); setSuccess(false);
          }}>Hủy thay đổi</button>
          <button type="submit" className="button button-primary" disabled={saving || !dirty}><Save size={17} aria-hidden /> {saving ? 'Đang lưu…' : 'Lưu cài đặt'}</button>
        </div>
      </div>
    </form>
  );
}

export function Settings() {
  const result = useResource(loadSettings);
  return (
    <>
      <PageHeading title="Cài đặt hệ thống" description="Quản lý ngưỡng lái xe, thời gian nghỉ, vị trí và chính sách lưu trữ dữ liệu."
        eyebrow={<><Settings2 size={14} aria-hidden /> QUẢN LÝ ĐỘI XE</>} />
      {result.loading && <div className="card"><Loading /></div>}
      {result.error && <div className="card"><ErrorState message={result.error} retry={result.retry} /></div>}
      {result.data && <SettingsForm initial={result.data} />}
    </>
  );
}
