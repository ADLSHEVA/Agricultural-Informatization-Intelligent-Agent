"use client";

import { useState } from "react";
import Link from "next/link";
import { api, type TermsReview } from "@/lib/api";
import { BigButton } from "@/components/BigButton";

const SAMPLE = `Heartland Grain LLC — Data Terms for Crop Year 2026

By delivering grain you grant Heartland Grain a perpetual, irrevocable licence
to resell, sublicense and otherwise monetize the following farm records, and to
share them with unnamed third parties:

- parcel / field identification
- date of each plant-protection application
- product name and application rate
- unsprayed filter strip / watercourse buffer
- yield (bushels per acre)
- revenue / crop sale value of the lot

Records are retained indefinitely. No deletion is offered.
`;

export default function TermsPage() {
  const [text, setText] = useState("");
  const [partner, setPartner] = useState("Heartland Grain LLC");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [card, setCard] = useState<TermsReview | null>(null);

  async function review() {
    if (!text.trim()) {
      setErr("Paste the clause first.");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const out = await api.reviewTerms({
        text,
        partner_name: partner.trim() || undefined,
      });
      setCard(out);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <p className="eyebrow">Plain-language check</p>
        <h1>Understand their data terms.</h1>
        <p className="muted">
          Gemini highlights resale, retention, third parties, and fields claimed. This is a reading, not consent; nothing is shared from this screen.{" "}
          <Link href="/receipts">Back to Sharing</Link>
        </p>
      </div>

      <div className="split">
        <section className="card">
          <h2>Paste the clause you received</h2>
          <label htmlFor="partner">Who sent this</label>
          <input id="partner" value={partner} onChange={(e) => setPartner(e.target.value)} />
          <label htmlFor="clause">Paste it</label>
          <textarea
            id="clause"
            rows={12}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste the data terms they sent…"
          />
          <div className="actions">
            <BigButton kind="ghost" onClick={() => setText(SAMPLE)}>
              Paste a sample resale clause
            </BigButton>
            <BigButton disabled={busy} onClick={review}>
              {busy ? "Reading…" : "Explain these terms"}
            </BigButton>
          </div>
          {err && <p className="bad">{err}</p>}
        </section>

        {card ? (
          <section className="card">
            <h2>{card.partner_name}</h2>
            <p>{card.plain_summary}</p>
            <p>
              Resale: <strong>{card.resale}</strong>
              {" · "}
              Aggregation: <strong>{card.aggregation}</strong>
              {card.retention_days != null && (
                <>
                  {" · "}Keep for {card.retention_days} days
                </>
              )}
            </p>
            {card.red_flags.length > 0 && (
              <ul className="bad">
                {card.red_flags.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            )}
            {card.over_ask.length > 0 && (
              <p className="bad">Beyond what you have allowed: {card.over_ask.join(", ")}</p>
            )}
            {card.over_ask.length === 0 && (
              <p className="ok">They are not asking for more fields than you have already allowed.</p>
            )}
            {card.fields_claimed.length > 0 && (
              <p className="muted">They claim: {card.fields_claimed.join(", ")}</p>
            )}
          </section>
        ) : (
          <section className="card placeholder">
            <p className="eyebrow">Result</p>
            <h2>Your plain-language reading appears here</h2>
            <p>Origin will show what they can do with the data, how long they keep it, and whether the request exceeds your boundary.</p>
          </section>
        )}
      </div>
    </>
  );
}
