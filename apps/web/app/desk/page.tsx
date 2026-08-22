"use client";

import { useEffect, useState } from "react";
import { api, type RuleDraft } from "@/lib/api";
import { BigButton } from "@/components/BigButton";
import { UncontrolledFile } from "@/components/UncontrolledFile";

const FIELD_LABEL: Record<string, string> = {
  parcel_id: "field",
  date: "date",
  product_name: "product",
  rate: "rate",
  unit: "unit",
  buffer_m: "filter strip",
  buffer_ok: "strip check",
  gaec4_buffer_ok: "GAEC 4 check",
};

const SAMPLE = `HEARTLAND GRAIN LLC
2026 Crop Year Delivery Questionnaire — Riverside Farms

To issue this season's spray statement and receive your lot, please supply:

1. Parcel / field identification
2. Date of each plant-protection application
3. Product name and application rate (L/ha)
4. Width of the unsprayed filter strip at the watercourse (buffer)
5. Yield for the delivered lot (bushels per acre / tonnes per hectare)
6. Revenue / crop sale value of the lot
`;

export default function DeskPage() {
  const [rows, setRows] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [draft, setDraft] = useState<RuleDraft | null>(null);

  async function load() {
    try {
      setRows(await api.deskPacks());
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function sendQuestionnaire() {
    if (!text.trim() && !file) {
      setErr("Paste the form or attach a file.");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const form = new FormData();
      form.set("farm_id", "demo-farm");
      form.set("text", text);
      if (file) form.set("document", file);
      const out = await api.deskQuestionnaire(form);
      setDraft(out);
      setMsg("Draft sent to the farm. Nothing compiles until they approve it.");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const refused = draft?.refused_fields?.length ? draft.refused_fields : draft?.dropped_refused ?? [];

  return (
    <>
      <div className="page-head">
        <h1>Elevator desk</h1>
        <p className="muted">Ask for a spray statement, or send a questionnaire. The grower still decides.</p>
      </div>

      <div className="desk-grid">
      <section className="card">
        <h2>Send a questionnaire</h2>
        <p className="muted">
          Origin turns this into a draft pack. The grower still has to approve it. Yield and revenue never
          survive.
        </p>
        <label htmlFor="q-text">Form text</label>
        <textarea
          id="q-text"
          rows={8}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste the intake form…"
        />
        <label htmlFor="q-file">Or attach a file</label>
        <UncontrolledFile id="q-file" onFile={setFile} />
        <BigButton kind="ghost" onClick={() => setText(SAMPLE)}>
          Paste a sample form
        </BigButton>
        <BigButton disabled={busy} onClick={sendQuestionnaire}>
          {busy ? "Reading…" : "Send to the farm"}
        </BigButton>
        {draft && (
          <>
            <p>{draft.plain_summary}</p>
            {refused.length > 0 && (
              <p className="bad">Origin stripped {refused.join(", ")}. Those never leave the farm.</p>
            )}
            <p className="muted">Fields in the draft: {draft.pack?.fields?.join(", ")}</p>
          </>
        )}
      </section>

      <div>
      <h2>Current files</h2>
      {err && <p className="bad">{err}</p>}
      {msg && <p className="ok">{msg}</p>}
      <BigButton
        kind="ghost"
        disabled={asking}
        onClick={async () => {
          setAsking(true);
          setErr("");
          setMsg("");
          try {
            const res = await api.deskRequest();
            const decision = res?.agent?.decision;
            setMsg(
              decision === "auto_deliver"
                ? "Asked again — Origin sent the current spray statement under standing permission."
                : "Asked the farm. Waiting on the grower.",
            );
            await load();
          } catch (e: any) {
            setErr(e.message);
          } finally {
            setAsking(false);
          }
        }}
      >
        {asking ? "Asking…" : "Ask the farm again"}
      </BigButton>
      {rows.length === 0 && !asking && <p className="muted">No file from this farm yet.</p>}
      {rows.map((r) => {
        const fields = r.pack?.fields ?? {};
        const names: string[] = Array.isArray(fields) ? fields : Object.keys(fields);
        const labels = names.map((n) => FIELD_LABEL[n] || n.replace(/_/g, " "));
        const until = r.consent?.until ? `Until ${r.consent.until}` : "";
        return (
          <section key={r.consent?.id ?? r.pack?.id} className={`card ${r.grey ? "greyed" : ""}`}>
            <h2>{r.grey ? "No longer available" : "This season's spray statement"}</h2>
            {r.grey ? (
              <p className="bad">Revoked, expired, or refused — the fields are gone.</p>
            ) : (
              <>
                <p>{labels.join(" · ") || "No fields"}</p>
                <p className="muted">
                  {until}
                  {until ? " · " : ""}
                  Yield and revenue are not in this file.
                </p>
              </>
            )}
          </section>
        );
      })}
      </div>
      </div>
    </>
  );
}
