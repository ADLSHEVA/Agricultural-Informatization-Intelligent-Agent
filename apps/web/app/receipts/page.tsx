"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { BigButton } from "@/components/BigButton";

export default function ReceiptsPage() {
  const [rows, setRows] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  function load() {
    api.receipts().then(setRows).catch((e) => setErr(e.message));
  }

  useEffect(load, []);

  async function revoke(id: string) {
    try {
      await api.revoke(id);
      load();
    } catch (e: any) {
      setErr(e.message);
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
    await api.eraseMe();
    load();
    setMsg("Erased. Tokens are dead.");
  }

  return (
    <>
      <h1>Who has it</h1>
      {rows.length === 0 && <p className="muted">No shares yet.</p>}
      {rows.map((r) => (
        <section key={r.id} className={`card ${r.grey ? "greyed" : ""}`}>
          <h2>{r.partner_name}</h2>
          <p className="muted">
            {r.kind === "refused" ? "You said no" : "You shared"} · {r.field_list?.join(", ")}
          </p>
          <p className="muted">{r.issued_at}</p>
          {r.kind === "given" && !r.grey && (
            <BigButton kind="danger" onClick={() => revoke(r.consent_id)}>
              Revoke
            </BigButton>
          )}
          {r.grey && <p className="ok">They can no longer open this file.</p>}
        </section>
      ))}
      {err && <p className="bad">{err}</p>}
      {msg && <p className="ok">{msg}</p>}
      <BigButton kind="ghost" onClick={exp}>
        Export my data
      </BigButton>
      <BigButton kind="danger" onClick={erase}>
        Erase my data
      </BigButton>
    </>
  );
}
