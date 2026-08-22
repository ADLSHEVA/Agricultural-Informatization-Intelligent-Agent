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
};

function groupReceipts(rows: any[]): Group[] {
  const map = new Map<string, any[]>();
  for (const r of rows) {
    const key = r.partner_name || r.consent_id;
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
    if (!confirm("Erase stored facts and evidence? Receipts stay as stubs.")) return;
    setBusy(true);
    try {
      await api.eraseMe();
      await load();
      setMsg("Erased. Tokens are dead.");
    } finally {
      setBusy(false);
    }
  }

  const groups = groupReceipts(rows);

  return (
    <>
      <div className="page-head">
        <h1>Who has it</h1>
        {err && <p className="bad">{err}</p>}
        {msg && <p className="ok">{msg}</p>}
        {groups.length === 0 && <p className="muted">No shares yet.</p>}
      </div>
      <div className="card-grid">
        {groups.map((g) => {
          const r = g.latest;
          return (
            <section key={g.key} className={`card ${r.grey ? "greyed" : ""}`}>
              <h2>{g.partner_name}</h2>
              <p className="muted">
                {r.kind === "refused" ? "You said no" : "You shared"} · {r.field_list?.join(", ")}
              </p>
              <p className="muted">
                {r.issued_at}
                {g.earlier > 0 ? ` · ${g.earlier} earlier ${g.earlier === 1 ? "time" : "times"}` : ""}
              </p>
              {g.liveIds.length > 0 && (
                <BigButton kind="danger" disabled={busy} onClick={() => revokeAll(g.liveIds)}>
                  {busy ? "Revoking…" : "Revoke"}
                </BigButton>
              )}
              {g.liveIds.length === 0 && <p className="ok">They can no longer open this file.</p>}
            </section>
          );
        })}
      </div>
      <div className="actions">
        <BigButton kind="ghost" onClick={() => router.push("/terms")}>
          Read their terms
        </BigButton>
        <BigButton kind="ghost" onClick={exp}>
          Export my data
        </BigButton>
        <BigButton kind="danger" onClick={erase}>
          Erase my data
        </BigButton>
      </div>
    </>
  );
}
