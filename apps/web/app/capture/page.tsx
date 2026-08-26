"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { BigButton } from "@/components/BigButton";
import { UncontrolledFile } from "@/components/UncontrolledFile";

type Draft = {
  id: string;
  time: string;
  parcel_id: string;
  product_name: string;
  rate: number | null;
  unit: string;
  buffer_m: number | null;
  note: string;
  confidence: number;
  provenance: Record<string, any>;
};

export default function CapturePage() {
  const router = useRouter();
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const [holding, setHolding] = useState(false);
  const [audio, setAudio] = useState<Blob | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [parcel, setParcel] = useState("p3");
  const [parcels, setParcels] = useState<any[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .today()
      .then((t) => {
        if (t.parcels?.length) setParcels(t.parcels);
      })
      .catch(() => undefined);
  }, []);

  async function startHold() {
    setErr("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunks.current = [];
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setAudio(new Blob(chunks.current, { type: mr.mimeType || "audio/webm" }));
      };
      rec.current = mr;
      mr.start();
      setHolding(true);
    } catch {
      setErr("Mic blocked — type the three facts below instead.");
    }
  }

  function stopHold() {
    rec.current?.stop();
    setHolding(false);
  }

  async function send() {
    setBusy(true);
    setErr("");
    try {
      const form = new FormData();
      form.set("parcel_id", parcel);
      form.set("note", note);
      if (audio) form.set("audio", audio, "voice.webm");
      if (image) form.set("image", image);
      const ev = await api.postEvent(form);
      setDraft({
        id: ev.id,
        time: ev.time,
        parcel_id: ev.parcel_id || parcel,
        product_name: ev.product_name ?? "",
        rate: ev.rate ?? null,
        unit: ev.unit || "L/ha",
        buffer_m: ev.buffer_m ?? null,
        note: ev.note ?? "",
        confidence: ev.confidence ?? 0,
        provenance: ev.provenance ?? {},
      });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!draft) return;
    setBusy(true);
    try {
      const res = await api.confirmEvent(draft.id, {
        product_name: draft.product_name,
        rate: draft.rate,
        unit: draft.unit,
        buffer_m: draft.buffer_m,
        note: draft.note,
        parcel_id: draft.parcel_id,
      });
      if (res.saved_only) {
        router.push("/?saved=1");
        return;
      }
      router.push(res.auto ? "/receipts" : `/consent/${res.consent.id}`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (draft) {
    return (
      <>
        <div className="page-head">
          <h1>Is this right?</h1>
          <p className="muted">Fix at most a few words. You are the source of truth.</p>
        </div>
        <section className="card">
          <div className="fields-2">
            <div>
              <label>Parcel</label>
              <select
                value={draft.parcel_id || "p3"}
                onChange={(e) => setDraft({ ...draft, parcel_id: e.target.value })}
              >
                {(parcels.length ? parcels : [{ id: "p3", label: "Ditch 40", crop: "corn" }]).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label} · {p.crop}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>Date and time</label>
              <input value={draft.time ? new Date(draft.time).toLocaleString() : ""} readOnly />
            </div>
            <div>
              <label>Product</label>
              <input
                value={draft.product_name ?? ""}
                onChange={(e) => setDraft({ ...draft, product_name: e.target.value })}
              />
            </div>
            <div>
              <label>Rate</label>
              <input
                type="number"
                step="0.1"
                value={draft.rate ?? ""}
                onChange={(e) => setDraft({ ...draft, rate: e.target.value ? Number(e.target.value) : null })}
              />
            </div>
            <div>
              <label>Unit</label>
              <input
                value={draft.unit ?? ""}
                onChange={(e) => setDraft({ ...draft, unit: e.target.value })}
              />
            </div>
            <div>
              <label>Buffer (m)</label>
              <input
                type="number"
                step="0.5"
                value={draft.buffer_m ?? ""}
                onChange={(e) => setDraft({ ...draft, buffer_m: e.target.value ? Number(e.target.value) : null })}
              />
            </div>
          </div>
        </section>
        <section className="card provenance">
          <h2>How this draft was read</h2>
          <p>
            <strong>{draft.provenance?.mode === "vertex" ? "Vertex AI" : "Deterministic fallback"}</strong>
            {draft.provenance?.model ? ` · ${draft.provenance.model}` : ""}
            {draft.provenance?.location ? ` · ${draft.provenance.location}` : ""}
          </p>
          <p className="muted">
            Extraction confidence: {Math.round((draft.confidence ?? 0) * 100)}%. The derived filter-strip
            check is deterministic and will be shown on the consent card before anything is shared.
          </p>
        </section>
        {err && <p className="bad">{err}</p>}
        <div className="actions">
          <BigButton disabled={busy} onClick={confirm}>
            That’s right
          </BigButton>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <h1>Speak or snap</h1>
        <p className="muted">Hold to talk, or photograph the can. One event only.</p>
      </div>
      <div className="split">
        <section className="card">
          <h2>Record</h2>
          <BigButton
            className={`big hold ${holding ? "rec" : ""}`}
            kind="ghost"
            onMouseDown={startHold}
            onMouseUp={stopHold}
            onTouchStart={(e) => {
              e.preventDefault();
              startHold();
            }}
            onTouchEnd={stopHold}
          >
            {holding ? "Listening…" : audio ? "Recorded — tap send" : "Hold to talk"}
          </BigButton>
          <label>Photo of the can</label>
          <UncontrolledFile accept="image/*" capture="environment" onFile={setImage} />
        </section>
        <section className="card">
          <h2>Or type it</h2>
          <label>Parcel</label>
          <select value={parcel} onChange={(e) => setParcel(e.target.value)}>
            {(parcels.length ? parcels : [{ id: "p3", label: "P3", crop: "wheat" }]).map((p) => (
              <option key={p.id} value={p.id}>
                {p.label} · {p.crop}
              </option>
            ))}
          </select>
          <label>Note</label>
          <textarea
            rows={5}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Field 3, product X, 1.2 L/ha, 16 ft strip by the ditch"
          />
          {err && <p className="bad">{err}</p>}
          <BigButton disabled={busy} onClick={send}>
            {busy ? "Reading…" : "Send"}
          </BigButton>
        </section>
      </div>
    </>
  );
}
