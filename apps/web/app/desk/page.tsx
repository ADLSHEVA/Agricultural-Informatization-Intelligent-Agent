"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { BigButton } from "@/components/BigButton";

export default function DeskPage() {
  const [rows, setRows] = useState<any[]>([]);
  const [msg, setMsg] = useState("");

  function load() {
    api.deskPacks().then(setRows).catch((e) => setMsg(e.message));
  }

  useEffect(load, []);

  return (
    <>
      <h1>Elevator desk</h1>
      <p className="muted">Growers never see this screen. Heartland Grain only.</p>
      <BigButton
        kind="ghost"
        onClick={async () => {
          const res = await api.deskRequest();
          const decision = res?.agent?.decision;
          setMsg(
            decision === "auto_deliver"
              ? "Asked again — Origin agent sent the pack under standing permission."
              : "Asked the farm for this season’s spray statement.",
          );
          load();
        }}
      >
        Ask the farm again
      </BigButton>
      {rows.map((r, i) => (
        <section key={i} className={`card ${r.grey ? "greyed" : ""}`}>
          <h2>{r.consent?.partner_name}</h2>
          <p>
            State: <strong>{r.consent?.state}</strong>
          </p>
          {r.grey ? (
            <p className="bad">File greyed out — revoke, expiry, or refuse.</p>
          ) : (
            <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(r.pack?.fields ?? {}, null, 2)}</pre>
          )}
        </section>
      ))}
      {msg && <p className="muted">{msg}</p>}
    </>
  );
}
