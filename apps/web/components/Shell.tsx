"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

function TabIcon({ name }: { name: "today" | "speak" | "who" }) {
  if (name === "today") {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <rect x="4" y="5" width="16" height="15" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M8 3v4M16 3v4M4 10h16" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  }
  if (name === "speak") {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <rect x="9" y="3" width="6" height="11" rx="3" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M6 11a6 6 0 0 0 12 0M12 17v4" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <circle cx="12" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M5 20c1.5-4 4-6 7-6s5.5 2 7 6" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

function FarmerLinks({
  path,
  who,
  className,
}: {
  path: string;
  who: boolean;
  className: string;
}) {
  return (
    <nav className={className} aria-label="Farmer">
      <Link className={path === "/" ? "active" : ""} href="/" aria-current={path === "/" ? "page" : undefined}>
        <TabIcon name="today" />
        Today
      </Link>
      <Link
        className={path.startsWith("/capture") ? "active" : ""}
        href="/capture"
        aria-current={path.startsWith("/capture") ? "page" : undefined}
      >
        <TabIcon name="speak" />
        Speak
      </Link>
      <Link className={who ? "active" : ""} href="/receipts" aria-current={who ? "page" : undefined}>
        <TabIcon name="who" />
        Who
      </Link>
    </nav>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const farmer = !path.startsWith("/desk");
  const who = path.startsWith("/receipts") || path.startsWith("/terms");

  return (
    <div className={farmer ? "portal" : "desk-stage"}>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <Link href={farmer ? "/" : "/desk"} className="wordmark">
          Origin
        </Link>
        {farmer ? (
          <FarmerLinks path={path} who={who} className="topnav" />
        ) : (
          <p className="desk-kicker">Heartland Grain LLC · partner desk · growers never see this screen</p>
        )}
      </header>
      <div className={farmer ? "work" : "desk-frame"}>
        <main id="main" className="shell">
          {children}
        </main>
      </div>
      {farmer && <FarmerLinks path={path} who={who} className="nav" />}
    </div>
  );
}
