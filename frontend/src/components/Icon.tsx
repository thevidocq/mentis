// One icon family: 24x24 viewBox, stroke 2, round caps and joins, currentColor.

const PATHS: Record<string, JSX.Element> = {
  plus: <><path d="M12 5v14" /><path d="M5 12h14" /></>,
  pencil: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></>,
  trash: <><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6" /><path d="M14 11v6" /></>,
  lock: <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>,
  x: <><path d="M6 6l12 12" /><path d="M18 6L6 18" /></>,
  alert: <><path d="M12 3l9 16H3z" /><path d="M12 10v4" /><path d="M12 17h.01" /></>,
  check: <><circle cx="12" cy="12" r="9" /><path d="M8 12l3 3 5-6" /></>,
  arrowLeft: <><path d="M19 12H5" /><path d="M11 6l-6 6 6 6" /></>,
  chevronRight: <path d="M9 6l6 6-6 6" />,
  tenants: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18" /><path d="M9 10v10" /></>,
  book: <><path d="M4 19V5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2z" /><path d="M8 7h6" /></>,
  chip: <><rect x="5" y="5" width="14" height="14" rx="2" /><path d="M9 9h6v6H9z" /><path d="M9 2v3" /><path d="M15 2v3" /><path d="M9 19v3" /><path d="M15 19v3" /><path d="M2 9h3" /><path d="M2 15h3" /><path d="M19 9h3" /><path d="M19 15h3" /></>,
  database: <><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></>,
  pulse: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  list: <><path d="M8 6h13" /><path d="M8 12h13" /><path d="M8 18h13" /><path d="M3 6h1" /><path d="M3 12h1" /><path d="M3 18h1" /></>,
  users: <><circle cx="9" cy="8" r="4" /><path d="M2 21a7 7 0 0 1 14 0" /><path d="M17 4a4 4 0 0 1 0 8" /><path d="M22 21a7 7 0 0 0-4-6.3" /></>,
  mail: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></>,
  file: <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></>,
  link: <><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" /></>,
  brain: <><path d="M9 3a3 3 0 0 0-3 3v1a3 3 0 0 0-2 5 3 3 0 0 0 2 5v1a3 3 0 0 0 6 0V3z" /><path d="M15 3a3 3 0 0 1 3 3v1a3 3 0 0 1 2 5 3 3 0 0 1-2 5v1a3 3 0 0 1-6 0" /></>,
  sliders: <><path d="M4 6h16" /><path d="M4 12h16" /><path d="M4 18h16" /><circle cx="9" cy="6" r="2" /><circle cx="15" cy="12" r="2" /><circle cx="7" cy="18" r="2" /></>,
  key: <><circle cx="8" cy="15" r="4" /><path d="M11 12l9-9" /><path d="M17 6l3 3" /></>,
  logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" /></>,
  chat: <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z" />,
  send: <><path d="M5 12h14" /><path d="M13 6l6 6-6 6" /></>,
  refresh: <><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></>,
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}
