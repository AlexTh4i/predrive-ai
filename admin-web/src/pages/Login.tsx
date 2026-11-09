import { Activity, AlertCircle, ArrowRight, Eye, EyeOff, FlaskConical, LoaderCircle, LockKeyhole, ShieldCheck, UserRound, UsersRound } from 'lucide-react';
import { useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { isMock } from '../api';
import { DEMO_PASSWORD } from '../api/demoCredentials';
import { ParrotMascot } from '../components/ParrotMascot';
import { useAuth } from '../hooks/useAuth';
import { errorMessage } from '../hooks/useResource';

export function Login() {
  const { login, user } = useAuth();
  const { state } = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const next = typeof state?.from === 'string' && /^\/(?!\/)/.test(state.from) ? state.from : '/';

  if (user) return <Navigate to={next} replace />;
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setError('');
    setSubmitting(true);
    try { await login(username.trim(), password); }
    catch (error) { setError(errorMessage(error)); }
    finally { setSubmitting(false); }
  }

  return (
    <main className="login-layout">
      <section className="login-story" aria-labelledby="login-story-heading">
        <div className="login-brand"><span className="brand-mascot"><ParrotMascot mood="peek" /></span><span>PreDrive <b>AI</b><small>ĐIỀU HÀNH ĐỘI XE</small></span></div>
        <div className="login-story-content">
          <div className="login-illustration"><ParrotMascot mood="peek" /><span className="login-radar"><Activity size={26} aria-hidden /></span></div>
          <h2 id="login-story-heading">Hệ thống giám sát tài xế</h2>
          <p>Theo dõi đội xe, nhận cảnh báo nguy hiểm và ghi nhận liên hệ trong cùng một ca trực.</p>
        </div>
        <div className="login-story-footer"><ShieldCheck size={18} aria-hidden /> Dành cho quản lý và người trực nhà xe</div>
      </section>
      <section className="login-main" aria-labelledby="login-heading">
        <div className="login-panel">
          <div className="login-mobile-brand"><span className="brand-mascot"><ParrotMascot mood="peek" /></span> PreDrive AI</div>
          <div className="eyebrow login-eyebrow"><LockKeyhole size={15} aria-hidden /> TRUNG TÂM ĐIỀU HÀNH</div>
          <h1 id="login-heading">Đăng nhập</h1>
          <p>Nhập tài khoản để vào bảng điều hành đội xe.</p>
          <form className="login-form" onSubmit={submit} aria-busy={submitting}>
            <label htmlFor="username">Tên đăng nhập</label>
            <div className="login-input"><UserRound size={17} aria-hidden />
              <input id="username" autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder="Nhập tên đăng nhập" value={username}
                onChange={(event) => { setUsername(event.target.value); setError(''); }} disabled={submitting} required />
            </div>
            <label htmlFor="password">Mật khẩu</label>
            <div className="login-input"><LockKeyhole size={17} aria-hidden />
              <input id="password" type={visible ? 'text' : 'password'} autoComplete="current-password" placeholder="Nhập mật khẩu"
                value={password} onChange={(event) => { setPassword(event.target.value); setError(''); }} disabled={submitting} required />
              <button className="icon-button" type="button" aria-label={visible ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'} aria-controls="password" onClick={() => setVisible(!visible)}>
                {visible ? <EyeOff size={17} aria-hidden /> : <Eye size={17} aria-hidden />}
              </button>
            </div>
            {error && <p className="login-error field-error" role="alert"><AlertCircle size={17} aria-hidden />{error}</p>}
            <button type="submit" className="button button-primary login-submit" disabled={submitting}>
              {submitting ? 'Đang đăng nhập…' : 'Đăng nhập'} {submitting ? <LoaderCircle className="spin" size={18} aria-hidden /> : <ArrowRight size={18} aria-hidden />}
            </button>
          </form>
          {isMock && <div className="demo-credentials">
            <div className="demo-heading"><FlaskConical size={16} aria-hidden /> <strong>Tài khoản mô phỏng</strong></div>
            <p>Chọn vai trò để điền thông tin đăng nhập.</p>
            <div className="demo-options">
              {([{ user: 'manager', label: 'Quản lý', icon: ShieldCheck }, { user: 'dispatcher', label: 'Người trực', icon: UsersRound }]).map((demo) => (
                <button key={demo.user} className="button button-secondary" type="button" disabled={submitting} onClick={() => {
                  setUsername(demo.user); setPassword(DEMO_PASSWORD); setError('');
                }}><demo.icon size={16} aria-hidden />{demo.label}</button>
              ))}
            </div>
          </div>}
        </div>
      </section>
    </main>
  );
}
