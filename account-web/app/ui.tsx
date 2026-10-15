// SPDX-License-Identifier: AGPL-3.0-or-later
// Shared marks and icons. Server-rendered SVG only: nothing here needs script.

/** Saiph's mark: three stars joined by a string, cyan through to violet. */
export function Mark({id, size = 28}: {id: string; size?: number}) {
  return <svg className="mark" width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
    <defs>
      <linearGradient id={id + "-s"} x1="8" y1="29" x2="32" y2="11" gradientUnits="userSpaceOnUse">
        <stop offset="0" stopColor="#22d3ee" /><stop offset=".5" stopColor="#f0f5ff" /><stop offset="1" stopColor="#b9a6fb" />
      </linearGradient>
      <radialGradient id={id + "-g"}><stop offset="0" stopColor="#5fe6f7" stopOpacity=".5" /><stop offset="1" stopColor="#5fe6f7" stopOpacity="0" /></radialGradient>
    </defs>
    <circle cx="20" cy="20" r="11" fill={`url(#${id}-g)`} />
    <path d="M8 29Q14 24.5 20 20Q26 15.5 32 11" fill="none" stroke={`url(#${id}-s)`} strokeOpacity=".35" strokeWidth=".9" />
    <path d="M8 29Q15.3 26.5 20 20Q24.7 13.5 32 11" fill="none" stroke={`url(#${id}-s)`} strokeWidth="1.6" strokeLinecap="round" />
    <circle cx="8" cy="29" r="2.6" fill="#5fe6f7" /><circle cx="20" cy="20" r="3" fill="#f0f5ff" /><circle cx="32" cy="11" r="2.6" fill="#b9a6fb" />
  </svg>;
}

/** Three strands drifting slowly under a hero; both ends fade into the page. */
export function Strings() {
  const strand = (amp: number, y: number) => {
    let d = `M0 ${y}`;
    for (let x = 0; x < 2400; x += 200) d += ` q50 ${-amp} 100 0 t100 0`;
    return d;
  };
  return <div className="strings" aria-hidden="true">
    <svg viewBox="0 0 2400 120" preserveAspectRatio="none">
      <defs>
        <linearGradient id="strings-g" x1="0" x2="1">
          <stop offset="0" stopColor="#22d3ee" /><stop offset=".25" stopColor="#7cb4fb" /><stop offset=".5" stopColor="#b9a6fb" />
          <stop offset=".75" stopColor="#7cb4fb" /><stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <path d={strand(26, 60)} fill="none" stroke="url(#strings-g)" strokeWidth="1.4" strokeOpacity=".55" />
      <path d={strand(14, 64)} fill="none" stroke="url(#strings-g)" strokeWidth="1" strokeOpacity=".3" />
      <path d={strand(-18, 58)} fill="none" stroke="url(#strings-g)" strokeWidth=".8" strokeOpacity=".22" />
    </svg>
  </div>;
}

const paths = {
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  external: <><path d="M14 4h6v6" /><path d="M20 4 10 14" /><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" /></>,
  lock: <><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>,
  check: <><circle cx="12" cy="12" r="9" /><path d="m8 12 3 3 5-6" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></>,
  windows: <><path d="M3 5.5 10.5 4.5v7H3zM12 4.3 21 3v8.5h-9zM3 12.5h7.5v7L3 18.5zM12 12.5h9V21l-9-1.3z" /></>,
  linux: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8M12 17v4M7 9l3 2-3 2M12 13h4" /></>,
  android: <><rect x="6" y="2.5" width="12" height="19" rx="2.5" /><path d="M10.5 18.5h3" /></>,
  book: <><path d="M4 5a2 2 0 0 1 2-2h13v15H6a2 2 0 0 0-2 2z" /><path d="M4 20a2 2 0 0 0 2 2h13v-4" /></>,
  card: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 10h18M7 15h4" /></>,
  devices: <><rect x="2" y="5" width="13" height="10" rx="1.5" /><path d="M5 19h7" /><rect x="17" y="8" width="5" height="11" rx="1.2" /></>,
  key: <><circle cx="8" cy="15" r="4" /><path d="m11 12 9-9M17 6l3 3" /></>,
};
export type IconName = keyof typeof paths;
export function Icon({name}: {name: IconName}) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

/** Google's "G", as its sign-in branding guidelines require on the button. */
export function GoogleMark() {
  return <svg viewBox="0 0 48 48" width="20" height="20" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
    <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
    <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
    <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
  </svg>;
}

/** A one-line piece of news at the top of a page. */
export function Notice({tone = "info", title, children}: {tone?: "info" | "neutral" | "warn"; title: string; children?: React.ReactNode}) {
  return <div className={tone === "info" ? "notice" : "notice " + tone} role="status">
    <Icon name={tone === "info" ? "check" : "info"} />
    <div><strong>{title}</strong>{children && <p>{children}</p>}</div>
  </div>;
}
