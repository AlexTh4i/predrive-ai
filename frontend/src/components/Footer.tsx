import React from 'react';
import { AlertCircle } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer className="w-full border-t border-automotive-border/60 bg-automotive-card/30 py-3.5 px-4 mt-auto">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2.5 text-center sm:text-left">
        <div>
          <p className="text-[11px] font-medium text-slate-400">
            PREDRIVE AI &bull; Hệ thống AI giám sát dấu hiệu buồn ngủ và mất tập trung của tài xế
          </p>
          <p className="text-[10px] text-slate-500 font-mono">
            Frontend PWA v0.1 &bull; Phụ trách: Kenneth
          </p>
        </div>

        <div className="flex items-center gap-2 text-[10px] text-amber-400/90 bg-amber-950/20 px-2.5 py-1 rounded-md border border-amber-500/20 max-w-md text-left">
          <AlertCircle className="w-3.5 h-3.5 shrink-0 text-amber-400" />
          <span>
            Bản nghiên cứu MVP: Chỉ thử nghiệm với xe dừng hoặc môi trường mô phỏng.
          </span>
        </div>
      </div>
    </footer>
  );
};
