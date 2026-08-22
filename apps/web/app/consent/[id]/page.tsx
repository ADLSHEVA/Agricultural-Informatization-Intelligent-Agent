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
  return (
    <>
      <div className="page-head">
        <h1>Give or refuse</h1>
        {!talk && <p className="muted">Loading…</p>}
      </div>
      {talk && (
        <section className="card">
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
      {err && <p className="bad">{err}</p>}
      <label className="card standing">
        <input type="checkbox" checked={standing} onChange={(e) => setStanding(e.target.checked)} />
        <span>
          Do this automatically next time for {c?.partner_name ?? "this elevator"} this crop year. Origin
          will send the same kind of spray statement without asking again. You can revoke anytime.
        </span>
      </label>
      <div className="row">
        <BigButton disabled={busy || !c} onClick={give}>
          Give
        </BigButton>
        <BigButton kind="ghost" disabled={busy || !c} onClick={refuse}>
          Refuse
        </BigButton>
      </div>
    </>
  );
}
