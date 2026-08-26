"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { BigButton } from "@/components/BigButton";

export default function ConsentPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [c, setC] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [standing, setStanding] = useState(false);

  useEffect(() => {
    api.getConsent(id).then(setC).catch((e) => setErr(e.message));
  }, [id]);

  async function give() {
    setBusy(true);
    try {
      await api.bind(id, { standing });
      router.push("/receipts");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function refuse() {
    setBusy(true);
    try {
      await api.refuse(id);
      router.push("/receipts");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const talk = c?.plain_talk;
  const packFields = Object.entries(c?.pack_fields ?? {}) as Array<[string, any]>;
  const labels: Record<string, string> = {
    parcel_id: "Field",
    date: "Date",
    product_name: "Product",
    rate: "Rate",
    unit: "Unit",
    buffer_m: "Filter strip",
    buffer_ok: "Filter-strip check",
  };
  const shown = (value: any) => (typeof value === "boolean" ? (value ? "Pass" : "Fail") : String(value ?? "—"));
  return (
    <>
      <div className="page-head">
        <p className="eyebrow">Approval checkpoint</p>
        <h1>Review this share.</h1>
        <p className="muted">Nothing leaves Origin until you approve the recipient, purpose, and exact values below.</p>
        {!talk && <p className="muted">Loading…</p>}
      </div>
      {talk && (
        <section className="card">
          <h2>Request details</h2>
          <div className="facts">
            <p>
              <strong>Who</strong>
              <br />
              {talk.who}
            </p>
            <p>
              <strong>Why</strong>
              <br />
              {talk.why}
            </p>
            <p>
              <strong>What</strong>
              <br />
              {talk.what}
            </p>
            <p>
              <strong>Until</strong>
              <br />
              {talk.until}
            </p>
            <p>
              <strong>Reuse</strong>
              <br />
              {talk.reuse}
            </p>
          </div>
        </section>
      )}
      {packFields.length > 0 && (
        <section className="card provenance">
          <h2>Exactly what will leave Origin</h2>
          <div className="field-table">
            {packFields.map(([name, value]) => (
              <p key={name}>
                <span>{labels[name] || name.replace(/_/g, " ")}</span>
                <strong>{shown(value)}</strong>
              </p>
            ))}
          </div>
          <p className="exclusion-note">Yield and revenue are excluded. They will not be sent with this pack.</p>
        </section>
      )}
      {err && <p className="bad">{err}</p>}
      <label className="card standing">
        <input type="checkbox" checked={standing} onChange={(e) => setStanding(e.target.checked)} />
        <span>
          <strong>Save this exact boundary for routine repeats</strong>
          <br />
          Allow {c?.partner_name ?? "this elevator"} to receive only {packFields.map(([name]) => labels[name] || name).join(", ") || "the fields above"}
          for {String(c?.purpose ?? "this purpose").replace(/_/g, " ")} through {c?.until ?? "the stated date"}. A new purpose, recipient, or field always comes back to me.
        </span>
      </label>
      <div className="row">
        <BigButton disabled={busy || !c} onClick={give}>
          {busy ? "Working…" : "Approve and share"}
        </BigButton>
        <BigButton kind="ghost" disabled={busy || !c} onClick={refuse}>
          Do not share
        </BigButton>
      </div>
    </>
  );
}
