import React from 'react';
import { Play, Square, Clock, Activity } from 'lucide-react';

interface MonitoringControlsProps {
  isStreaming: boolean;
  formattedDuration: string;
  onStart: () => void;
  onStop: () => void;
}

export const MonitoringControls: React.FC<MonitoringControlsProps> = ({
  isStreaming,
  formattedDuration,
  onStart,
  onStop,
}) => {
  return (
    <div className="w-full bg-automotive-card border border-automotive-border rounded-2xl p-4 sm:p-5 shadow-card-glow flex flex-col sm:flex-row items-center justify-between gap-4">
      {/* Session Timer & Status Indicator */}
      <div className="flex items-center gap-3.5 w-full sm:w-auto">
        <div className={`w-11 h-11 rounded-xl flex items-center justify-center transition-all ${
          isStreaming 
            ? 'bg-cyan-950/60 border border-cyan-500/40 text-cyan-400 shadow-automotive-cyan' 
            : 'bg-slate-900 border border-slate-800 text-slate-500'
        }`}>
          {isStreaming ? (
            <Activity className="w-5 h-5 text-cyan-400 animate-pulse" />
          ) : (
            <Clock className="w-5 h-5" />
          )}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest block">
              THỜI LƯỢNG PHIÊN
            </span>
            <span className={`w-1.5 h-1.5 rounded-full ${isStreaming ? 'bg-emerald-400 animate-ping' : 'bg-slate-600'}`}></span>
          </div>
          <span className="text-2xl sm:text-3xl font-mono font-bold text-slate-100 tracking-tight block">
            {formattedDuration}
          </span>
        </div>
      </div>

      {/* Main Single Action Button */}
      <div className="w-full sm:w-auto">
        {!isStreaming ? (
          <button
            onClick={onStart}
            className="w-full sm:w-auto flex items-center justify-center gap-2.5 py-3 px-7 rounded-xl bg-gradient-to-r from-cyan-500 via-sky-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold text-sm sm:text-base shadow-automotive-cyan transition-all transform active:scale-[0.98] min-h-[48px]"
          >
            <Play className="w-4 h-4 fill-slate-950" />
            <span>BẮT ĐẦU GIÁM SÁT</span>
          </button>
        ) : (
          <button
            onClick={onStop}
            className="w-full sm:w-auto flex items-center justify-center gap-2.5 py-3 px-7 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-sm sm:text-base shadow-automotive-danger transition-all transform active:scale-[0.98] border border-rose-400/30 min-h-[48px]"
          >
            <Square className="w-4 h-4 fill-white" />
            <span>KẾT THÚC GIÁM SÁT</span>
          </button>
        )}
      </div>
    </div>
  );
};
