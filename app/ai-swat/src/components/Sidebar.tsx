import { NavLink } from 'react-router-dom';
import clsx from 'clsx';
import { MessageCircle, Settings, Sprout, Sliders } from 'lucide-react';

const nav = [
  { to: '/', icon: MessageCircle, label: 'Advisor' },
  { to: '/editor', icon: Sliders, label: 'SWAT+ Editor' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function Sidebar() {
  return (
    <aside className="w-16 bg-[var(--se-rail)] border-r border-[var(--se-border)] flex flex-col items-center h-full py-4">
      <div className="w-9 h-9 rounded-xl bg-[var(--se-accent)] flex items-center justify-center mb-6 shadow-sm" title="AI-SWAT+">
        <Sprout className="w-5 h-5 text-white" />
      </div>

      <nav className="flex-1 flex flex-col items-center gap-1.5">
        {nav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            title={label}
            className={({ isActive }) =>
              clsx(
                'w-10 h-10 rounded-xl flex items-center justify-center transition-colors',
                isActive
                  ? 'bg-[var(--se-accent-sf)] text-[var(--se-accent)]'
                  : 'text-[var(--se-text-mut)] hover:text-[var(--se-text)] hover:bg-[var(--se-card)]',
              )
            }
          >
            <Icon className="w-5 h-5" />
          </NavLink>
        ))}
      </nav>

      <div className="text-[9px] text-[var(--se-text-fnt)] tracking-wide">v0.3</div>
    </aside>
  );
}
