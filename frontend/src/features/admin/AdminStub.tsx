import React from 'react';
import { LayoutDashboard, Clock, AlertTriangle, Database, ShieldAlert, ArrowLeft } from 'lucide-react';

interface AdminStubProps {
  onBackToDriver?: () => void;
}

export const AdminStub: React.FC<AdminStubProps> = ({ onBackToDriver }) => {
  return (
    <div className="max-w-5xl mx-auto w-full p-3 sm:p-6 lg:p-8 animate-in fade-in duration-200">
      {/* Top Banner Navigation */}
      {onBackToDriver && (
        <button
          onClick={onBackToDriver}
          className="inline-flex items-center gap-1.5 text-xs font-mono text-cyan-400 hover:text-cyan-300 mb-4 sm:mb-6 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Quay lại giao diện giám sát tài xế</span>
        </button>
      )}

      {/* Header Panel */}
      <div className="bg-automotive-card border border-automotive-border rounded-2xl p-4 sm:p-6 lg:p-8 shadow-card-glow mb-4 sm:mb-6">
        <div className="flex items-center gap-3 mb-3 text-cyan-400">
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl bg-cyan-950/60 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-automotive-cyan shrink-0">
            <LayoutDashboard className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-bold text-slate-100 font-mono tracking-wide">
              ADMIN COCKPIT — QUẢN TRỊ ĐỘI XE
            </h2>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-800">
              Lộ trình Milestone M3 & M4
            </span>
          </div>
        </div>

        <p className="text-xs sm:text-sm text-slate-300 leading-relaxed max-w-3xl">
          Khu vực Quản trị viên phục vụ việc theo dõi tổng số <strong className="text-cyan-300">giờ giám sát hợp lệ</strong>, nhật ký sự kiện mất tập trung / buồn ngủ theo tài xế và cảnh báo Telegram sẽ được kích hoạt sau khi Backend hoàn thành cơ sở dữ liệu PostgreSQL/Supabase và hệ thống phân quyền (B3/B4).
        </p>
      </div>

      {/* Feature Architecture Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5 sm:gap-4">
        {/* Module 1 */}
        <div className="bg-automotive-card border border-automotive-border rounded-2xl p-4 sm:p-5 shadow-card-glow flex flex-col justify-between">
          <div>
            <div className="w-8 h-8 rounded-lg bg-sky-950/60 border border-sky-500/30 flex items-center justify-center text-sky-400 mb-2.5">
              <Clock className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold text-slate-100 mb-1">
              Thống kê Giờ giám sát
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Tính toán thời gian lái xe an toàn trên tổng số giờ giám sát hợp lệ, không đếm sự kiện thô.
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800/80 text-[10px] font-mono text-slate-500">
            Trạng thái: <span className="text-sky-400">Chờ Schema Trips</span>
          </div>
        </div>

        {/* Module 2 */}
        <div className="bg-automotive-card border border-automotive-border rounded-2xl p-4 sm:p-5 shadow-card-glow flex flex-col justify-between">
          <div>
            <div className="w-8 h-8 rounded-lg bg-amber-950/60 border border-amber-500/30 flex items-center justify-center text-amber-400 mb-2.5">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold text-slate-100 mb-1">
              Nhật ký Sự kiện An toàn
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Lưu trữ metadata các sự kiện buồn ngủ / mất tập trung để người quản lý rà soát đánh giá.
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800/80 text-[10px] font-mono text-slate-500">
            Trạng thái: <span className="text-amber-400">Chờ Schema Events</span>
          </div>
        </div>

        {/* Module 3 */}
        <div className="bg-automotive-card border border-automotive-border rounded-2xl p-4 sm:p-5 shadow-card-glow flex flex-col justify-between">
          <div>
            <div className="w-8 h-8 rounded-lg bg-emerald-950/60 border border-emerald-500/30 flex items-center justify-center text-emerald-400 mb-2.5">
              <Database className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold text-slate-100 mb-1">
              Quản lý Đội xe & Phân quyền
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Quản lý danh sách phương tiện, tổ chức và tài xế bảo mật theo phân quyền tổ chức.
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800/80 text-[10px] font-mono text-slate-500">
            Trạng thái: <span className="text-emerald-400">Chờ Backend Auth</span>
          </div>
        </div>
      </div>

      {/* Security notice */}
      <div className="mt-4 sm:mt-6 flex items-start gap-2.5 p-3 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400 leading-relaxed">
        <ShieldAlert className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
        <span>
          Nguyên tắc bảo vệ dữ liệu: Giao diện quản trị chỉ hiển thị metadata và sự kiện thống kê, tuyệt đối không lưu trữ hay hiển thị video thô khuôn mặt của tài xế.
        </span>
      </div>
    </div>
  );
};
