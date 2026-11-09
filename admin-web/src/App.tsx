import { lazy } from 'react';
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Empty, Loading, TextLink } from './components/ui';
import { useAuth } from './hooks/useAuth';
import { Drivers } from './pages/Drivers';
import { History } from './pages/History';
import { Login } from './pages/Login';
import { Settings } from './pages/Settings';

const Dashboard = lazy(() => import('./pages/Dashboard').then(({ Dashboard }) => ({ default: Dashboard })));
const DriverDetail = lazy(() => import('./pages/DriverDetail').then(({ DriverDetail }) => ({ default: DriverDetail })));
const Stats = lazy(() => import('./pages/Stats').then(({ Stats }) => ({ default: Stats })));

export function RequireOperator() {
  const { user, loading } = useAuth();
  const { pathname, search } = useLocation();
  if (loading) return <Loading label="Đang kiểm tra phiên đăng nhập…" />;
  return user ? <Outlet /> : <Navigate to="/login" state={{ from: pathname + search }} replace />;
}

function LoginRoute() {
  const { loading } = useAuth();
  return loading ? <Loading label="Đang kiểm tra phiên đăng nhập…" /> : <Login />;
}

function ManagerSettings() {
  const { user } = useAuth();
  return user?.role === 'manager' ? <Settings /> : (
    <div className="card"><Empty title="Bạn không có quyền truy cập cài đặt" description="Chỉ quản lý đội xe có quyền chỉnh sửa."
      action={<TextLink to="/">Về giám sát trực tiếp</TextLink>} /></div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route element={<RequireOperator />}>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="history" element={<History />} />
          <Route path="drivers" element={<Drivers />} />
          <Route path="drivers/:id" element={<DriverDetail />} />
          <Route path="stats" element={<Stats />} />
          <Route path="settings" element={<ManagerSettings />} />
          <Route path="*" element={<div className="card"><Empty title="Không tìm thấy trang"
            action={<TextLink to="/">Về giám sát trực tiếp</TextLink>} /></div>} />
        </Route>
      </Route>
    </Routes>
  );
}
