import { Activity, BarChart3, ChevronRight, CircleHelp, Clock3, FlaskConical, History, LogOut, Menu, Settings2, ShieldCheck, UsersRound, X } from 'lucide-react';
import { Suspense, useEffect, useRef } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { isMock } from '../api';
import { useAlarm } from '../hooks/useAlarm';
import { useAuth } from '../hooks/useAuth';
import { useClock } from '../hooks/useClock';
import { LiveFeedProvider, useFeed } from '../hooks/useLiveFeed';
import { formatClock, formatLongDate } from '../lib/format';
import { ParrotMascot } from './ParrotMascot';
import { Avatar, Loading } from './ui';

const navigation = [
  { to: '/', label: 'Giám sát trực tiếp', icon: Activity },
  { to: '/history', label: 'Lịch sử cảnh báo', icon: History },
  { to: '/drivers', label: 'Danh sách tài xế', icon: UsersRound },
  { to: '/stats', label: 'Thống kê', icon: BarChart3 },
  { to: '/settings', label: 'Cài đặt hệ thống', icon: Settings2, manager: true },
];

function Sidebar({ close }: { close?: () => void }) {
  const { user, logout } = useAuth();
  if (!user) return null;
  return (
    <div className="sidebar-content">
      <div className="brand-row">
        <Link to="/" className="brand" onClick={close}>
          <span className="brand-mascot"><ParrotMascot mood="peek" /></span>
          <span><strong>PreDrive<span className="brand-ai"> AI</span></strong><small>Hệ thống giám sát tài xế</small></span>
        </Link>
        {close && <button className="icon-button sidebar-close" onClick={close} aria-label="Đóng menu"><X size={19} aria-hidden /></button>}
      </div>
      <p className="sidebar-caption">ĐIỀU HÀNH ĐỘI XE</p>
      <nav className="sidebar-nav" aria-label="Điều hướng chính">
        {navigation.filter((item) => !item.manager || user.role === 'manager').map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'} onClick={close}>
            <Icon size={18} aria-hidden /><span>{label}</span><ChevronRight className="nav-chevron" size={14} aria-hidden />
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-mode">
          {isMock ? <FlaskConical size={17} aria-hidden /> : <ShieldCheck size={17} aria-hidden />}
          <div><strong>{isMock ? 'Chế độ mô phỏng' : 'Chế độ vận hành'}</strong>
            <small>{isMock ? 'Dữ liệu dùng để trình diễn' : 'Dữ liệu từ máy chủ'}</small>
          </div>
        </div>
        <div className="sidebar-user">
          <Avatar name={user.fullName} id={user.id} />
          <div><strong>{user.fullName}</strong><small>{user.role === 'manager' ? 'Quản lý' : 'Người trực'}</small></div>
          <button className="icon-button logout" onClick={logout} aria-label="Đăng xuất" title="Đăng xuất"><LogOut size={17} aria-hidden /></button>
        </div>
      </div>
    </div>
  );
}

function Topbar({ openMenu }: { openMenu: () => void }) {
  const { pathname } = useLocation();
  const { user } = useAuth();
  const { connection } = useFeed();
  const now = useClock();
  const current = navigation.find(({ to }) => to === pathname || (to !== '/' && pathname.startsWith(`${to}/`)));
  const label = connection === 'live' ? 'Trực tuyến' : connection === 'connecting' ? 'Đang kết nối…' : 'Đang kết nối lại…';
  return (
    <header className="topbar">
      <button className="icon-button mobile-menu" onClick={openMenu} aria-label="Mở menu" aria-haspopup="dialog" aria-controls="mobile-navigation"><Menu size={20} aria-hidden /></button>
      <nav className="breadcrumb" aria-label="Đường dẫn trang">
        {pathname !== '/' && <Link to="/">Trung tâm điều hành</Link>}
        {pathname !== '/' && <ChevronRight size={13} aria-hidden />}
        {current?.to === '/drivers' && pathname !== '/drivers'
          ? <><Link className="breadcrumb-parent" to="/drivers">Danh sách tài xế</Link><ChevronRight size={13} aria-hidden /><strong aria-current="page">Hồ sơ tài xế</strong></>
          : <strong aria-current="page">{current?.label ?? 'PreDrive AI'}</strong>}
      </nav>
      <div className="topbar-right">
        <span className="topbar-time" title={formatLongDate(now)}><Clock3 size={15} aria-hidden /> {formatClock(now)} <small>GMT+7</small></span>
        <span className={`connection connection-${connection}`} role="status"><span aria-hidden />{label}</span>
        {user && <div className="topbar-account">
          <Avatar name={user.fullName} id={user.id} />
          <span><strong>{user.fullName}</strong><small>{user.role === 'manager' ? 'Quản lý' : 'Người trực'}</small></span>
        </div>}
      </div>
    </header>
  );
}

export function Layout() {
  const alarm = useAlarm();
  const menu = useRef<HTMLDialogElement>(null);
  const main = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
    main.current?.focus({ preventScroll: true });
  }, [pathname]);
  useEffect(() => {
    const desktop = matchMedia('(min-width: 1024px)');
    const closeOnDesktop = () => { if (desktop.matches) menu.current?.close(); };
    desktop.addEventListener('change', closeOnDesktop);
    return () => desktop.removeEventListener('change', closeOnDesktop);
  }, []);
  return (
    <LiveFeedProvider onCritical={alarm.notify}>
      <a className="skip-link" href="#main-content">Đến nội dung chính</a>
      <aside className="sidebar"><Sidebar /></aside>
      <dialog id="mobile-navigation" ref={menu} className="mobile-sidebar" aria-label="Điều hướng" onClick={(event) => {
        if (event.target === event.currentTarget) menu.current?.close();
      }}>
        <Sidebar close={() => menu.current?.close()} />
      </dialog>
      <div className="workspace">
        <Topbar openMenu={() => menu.current?.showModal()} />
        <main id="main-content" className="page" tabIndex={-1} ref={main}>
          <Suspense fallback={<Loading label="Đang tải trang…" />}><Outlet context={alarm} /></Suspense>
        </main>
        <footer className="footer"><CircleHelp size={15} aria-hidden /> PreDrive AI hỗ trợ giám sát và cảnh báo. Tài xế cần tuân thủ quy định an toàn giao thông.</footer>
      </div>
    </LiveFeedProvider>
  );
}
