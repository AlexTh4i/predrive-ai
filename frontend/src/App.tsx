import { useEffect, useState } from 'react';
import { DriverScreen } from './features/driver/DriverScreen';
import { AdminStub } from './features/admin/AdminStub';

export function App() {
  const [view, setView] = useState<'driver' | 'admin'>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      if (params.get('view') === 'admin' || window.location.pathname.startsWith('/admin')) {
        return 'admin';
      }
    }
    return 'driver';
  });

  const goToAdmin = () => {
    setView('admin');
    window.history.pushState({}, '', '?view=admin');
  };

  const goToDriver = () => {
    setView('driver');
    window.history.pushState({}, '', window.location.pathname);
  };

  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      setView(params.get('view') === 'admin' ? 'admin' : 'driver');
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  if (view === 'admin') {
    return (
      <div className="min-h-screen bg-[#0e1318] text-slate-100 p-4">
        <AdminStub onBackToDriver={goToDriver} />
      </div>
    );
  }

  return <DriverScreen onOpenAdmin={goToAdmin} />;
}

export default App;
