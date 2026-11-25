export function LogoIcon({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 60 60" aria-hidden="true">
      <rect x="4" y="4" width="52" height="52" rx="14" fill="#0D9488" />
      <path d="M17 42 V19 L30 33 L43 19 V42" fill="none" stroke="#FFFFFF" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="30" cy="15" r="3.6" fill="#99F6E4" />
    </svg>
  );
}

export function Brand() {
  return (
    <div className="row" style={{ gap: 10 }}>
      <LogoIcon />
      <span className="brand-name">MENTIS</span>
    </div>
  );
}
