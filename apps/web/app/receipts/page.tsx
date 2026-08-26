"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { BigButton } from "@/components/BigButton";

type Group = {
  key: string;
  partner_name: string;
  latest: any;
  earlier: number;
  liveIds: string[];
  purpose: string;
};

function groupReceipts(rows: any[]): Group[] {
  const map = new Map<string, any[]>();
  for (const r of rows) {
    // partner_id is stable; older rows predate it and fall back to the name.
    const partner = r.partner_id || r.partner_name || r.consent_id;
    const key = `${partner}:${r.purpose || "unspecified"}`;
    const list = map.get(key) ?? [];
    list.push(r);
    map.set(key, list);
  }
  const groups: Group[] = [];
  for (const [key, list] of map) {
    list.sort((a, b) => String(b.issued_at || "").localeCompare(String(a.issued_at || "")));
    const latest = list[0];
    groups.push({
      key,
      partner_name: latest.partner_name,
      latest,
      earlier: Math.max(0, list.length - 1),
      liveIds: list.filter((r) => r.kind === "given" && !r.grey).map((r) => r.consent_id),
      purpose: latest.purpose || "unspecified purpose",
    });
  }
  groups.sort((a, b) => String(b.latest.issued_at || "").localeCompare(String(a.latest.issued_at || "")));
  return groups;
}

export default function ReceiptsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const sharedDemo =
    process.env.NEXT_PUBLIC_SHARED_DEMO !== "false" &&
    process.env.NEXT_PUBLIC_DEMO_MODE !== "false";

  async function load() {
    try {
      setRows(await api.receipts());
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function revokeAll(ids: string[]) {
    setBusy(true);
    setErr("");
    try {
      for (const id of ids) await api.revoke(id);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function exp() {
    const pack = await api.exportMe();
    const blob = new Blob([JSON.stringify(pack, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "origin-portable-pack.json";
    a.click();
    setMsg("Exported a portable copy of what you originated.");
  }

  async function erase() {
    if (
      !confirm(
        "Erase facts and evidence stored by Origin? Hash-only receipt stubs remain, and recipient deletion notices are recorded separately.",
      )
    )
      return;
    setBusy(true);
    try {
      await api.eraseMe();
      await load();
      setMsg("Origin's stored copy was erased. Future access is blocked; recipient notices were recorded.");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const groups = groupReceipts(rows);
  const activeShares = groups.filter((group) => group.liveIds.length > 0).length;

  return (
    <>
      <div className="page-head">
        <p className="eyebrow">Your data trail</p>
        <h1>Sharing and access.</h1>
        <p className="muted">See who received farm data, why they received it, and whether future access is still open.</p>
        {err && <p className="bad">{err}</p>}
        {msg && <p className="ok">{msg}</p>}
        {groups.length === 0 && <p className="muted">No shares yet.</p>}
      </div>
      {groups.length > 0 && (
        <section className="signal-grid" aria-label="Sharing summary">
          <div className="signal"><span className="signal-number">{groups.length}</span><span><small>Recipients</small><strong>In your audit trail</strong></span></div>
          <div className="signal"><span className={`signal-dot ${activeShares ? "attention" : "safe"}`} /><span><small>Future access</small><strong>{activeShares ? `${activeShares} active` : "All blocked"}</strong></span></div>
          <div className="signal"><span className="signal-dot live" /><span><small>Portable copy</small><strong>Ready to export</strong></span></div>
        </section>
      )}
      <div className="card-grid">
        {groups.map((g) => {
          const r = g.latest;
          return (
            <section key={g.key} className={`card ${r.grey ? "greyed" : ""}`}>
              <span className="task-label">{g.liveIds.length > 0 ? "Access active" : "Access closed"}</span>
              <h2>{g.partner_name}</h2>
              <p className="muted">
                {r.kind === "refused" ? "You said no" : "You shared"} · {g.purpose.replace(/_/g, " ")}
              </p>
              <p>{r.field_list?.join(", ") || "Hash-only receipt"}</p>
              <p className="muted">
                {r.issued_at}
                {r.until ? ` · access through ${r.until}` : ""}
                {g.earlier > 0 ? ` · ${g.earlier} earlier ${g.earlier === 1 ? "time" : "times"}` : ""}
              </p>
              {r.delivery?.status && (
                <p className="muted">
                  Delivery {r.delivery.status} · {(r.delivery.destinations || []).join(" · ")}
                </p>
              )}
              {g.liveIds.length > 0 && (
                <BigButton kind="danger" disabled={busy} onClick={() => revokeAll(g.liveIds)}>
                  {busy ? "Revoking…" : "Stop future access"}
                </BigButton>
              )}
              {g.liveIds.length === 0 && (
                <p className="ok">
                  Future access through Origin is blocked. Previously exported copies require recipient confirmation.
                </p>
              )}
            </section>
          );
        })}
      </div>
      <section className="card">
        <p className="eyebrow">Your copy</p>
        <h2>Portability and deletion</h2>
        <p className="muted">Export a machine-readable copy at any time. Erasing Origin-managed activity records also blocks future access, but cannot silently remove files a recipient already downloaded.</p>
        {sharedDemo && <p className="muted">Erasure is disabled here because this public hackathon site is a shared, synthetic tenant.</p>}
        <div className="actions">
        <BigButton kind="ghost" onClick={() => router.push("/terms")}>
          Check partner terms
        </BigButton>
        <BigButton kind="ghost" onClick={exp}>
          Export Origin's copy
        </BigButton>
        {!sharedDemo && (
          <BigButton kind="danger" onClick={erase}>
            Erase Origin's copy
          </BigButton>
        )}
        </div>
      </section>
    </>
  );
}
