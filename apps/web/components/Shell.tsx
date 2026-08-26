"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 40 40">
        <path d="M8 29c8-1 15-5 21-13" />
        <path d="M17 22c-5 .5-8-1.8-9-6.7 5-.8 8.5 1.5 9 6.7Z" />
        <path d="M22 19c.2-5.4 3-8.8 8.8-9.8.2 5.5-2.8 8.8-8.8 9.8Z" />
        <path d="M8 30h24" />
      </svg>
    </span>
  );
}

function TabIcon({ name }: { name: "today" | "record" | "sharing" }) {
  if (name === "today") {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path d="M4 11.5 12 5l8 6.5V20H4v-8.5Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M9 20v-5h6v5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    );
  }
  if (name === "record") {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path d="M6 19h12M8 16l8-8 2 2-8 8H8v-2Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="m14.5 9.5 2 2" fill="none" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path d="M7 8.5h10M7 12h10M7 15.5h6" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="4" y="4" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function FarmerLinks({ path, who, className }: { path: string; who: boolean; className: string }) {
  return (
    <nav className={className} aria-label="Farm workspace">
      <Link className={path === "/" ? "active" : ""} href="/" aria-current={path === "/" ? "page" : undefined}>
        <TabIcon name="today" />
        Today
      </Link>
      <Link
        className={path.startsWith("/capture") ? "active" : ""}
        href="/capture"
        aria-current={path.startsWith("/capture") ? "page" : undefined}
      >
        <TabIcon name="record" />
        Record
      </Link>
      <Link className={who ? "active" : ""} href="/receipts" aria-current={who ? "page" : undefined}>
        <TabIcon name="sharing" />
        Sharing
      </Link>
    </nav>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const farmer = !path.startsWith("/desk");
  const who = path.startsWith("/receipts") || path.startsWith("/terms");
  const [online, setOnline] = useState(true);

  useEffect(() => {
    const refresh = () => setOnline(navigator.onLine);
    refresh();
    window.addEventListener("online", refresh);
    window.addEventListener("offline", refresh);
    return () => {
      window.removeEventListener("online", refresh);
      window.removeEventListener("offline", refresh);
    };
  }, []);

  return (
    <div className={farmer ? "portal" : "desk-stage"}>
      <a className="skip" href="#main">
        Skip to content
      </a>
      {!online && (
        <div className="offline-banner" role="status">
          You are offline. Any typed field note stays in this browser until you reconnect and send it.
        </div>
      )}
      <header className="topbar">
        <Link href={farmer ? "/" : "/desk"} className="brand" aria-label="Origin home">
          <BrandMark />
          <span>
            <strong className="wordmark">Origin</strong>
            <small>{farmer ? "Farmer-controlled agent" : "Partner workspace"}</small>
          </span>
        </Link>
        {farmer ? <FarmerLinks path={path} who={who} className="topnav" /> : <p className="desk-kicker">Heartland Grain LLC</p>}
        {!farmer && (
          <Link className="context-switch" href="/">
            <span className="context-dot" aria-hidden="true" />
            Farm view
          </Link>
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
