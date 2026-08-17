"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const farmer = !path.startsWith("/desk");
  return (
    <div className="shell">
      {children}
      {farmer && (
        <nav className="nav">
          <Link className={path === "/" ? "active" : ""} href="/">
            Today
          </Link>
          <Link className={path.startsWith("/capture") ? "active" : ""} href="/capture">
            Speak
          </Link>
          <Link className={path.startsWith("/receipts") ? "active" : ""} href="/receipts">
            Who
          </Link>
        </nav>
      )}
    </div>
  );
}
