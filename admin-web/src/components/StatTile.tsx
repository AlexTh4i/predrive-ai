import { memo } from 'react';
import type { LucideIcon } from 'lucide-react';

export const StatTile = memo(function StatTile({ icon: Icon, label, value, description, tone = 'green' }: {
  icon: LucideIcon; label: string; value: string | number; description?: string;
  tone?: 'green' | 'amber' | 'red' | 'slate';
}) {
  return (
    <div className={`card stat-tile stat-${tone}`}>
      <p>{label}</p>
      <span className={`icon-tile tone-${tone}`}><Icon size={20} aria-hidden /></span>
      <strong>{value}</strong>
      {description && <small>{description}</small>}
    </div>
  );
});
