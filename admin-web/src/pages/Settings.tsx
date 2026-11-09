import { useState } from 'react';
import type { FormEvent } from 'react';
import { AlertCircle, Check, Clock3, Info, LoaderCircle, MapPin, Save, Settings2 } from 'lucide-react';
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
  const dirty = JSON.stringify(fields(saved)) !== JSON.stringify(draft);

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
    try {
      const updated = await api.updateSettings({
        ...saved, continuousWarnSec: warning, continuousCriticalSec: critical, restResetMin: rest, shareLocation: draft.shareLocation,
      });
      setSaved(updated);
      setDraft(fields(updated));
      applySettings(updated);
      setSuccess(true);
    } catch (error) {
      setError(errorMessage(error));
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
      <fieldset disabled={saving} className="card panel settings-panel" aria-label="Chia sẻ vị trí">
        <SectionHeading title="Chia sẻ vị trí" description="Cấu hình cho phép app tài xế gửi vị trí trong phiên giám sát."
          actions={<span className="icon-tile tone-green"><MapPin size={19} aria-hidden /></span>} />
        <label className="settings-switch">
          <span><strong>Cho phép chia sẻ vị trí</strong><small>Áp dụng cho các thiết bị của đội xe.</small></span>
          <input className="switch" type="checkbox" role="switch" checked={draft.shareLocation}
            aria-label="Cho phép chia sẻ vị trí" onChange={(event) => update('shareLocation', event.target.checked)} />
        </label>
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
      <PageHeading title="Cài đặt hệ thống" description="Quản lý ngưỡng lái xe, thời gian nghỉ và quyền chia sẻ vị trí."
        eyebrow={<><Settings2 size={14} aria-hidden /> QUẢN LÝ ĐỘI XE</>} />
      {result.loading && <div className="card"><Loading /></div>}
      {result.error && <div className="card"><ErrorState message={result.error} retry={result.retry} /></div>}
      {result.data && <SettingsForm initial={result.data} />}
    </>
  );
}
