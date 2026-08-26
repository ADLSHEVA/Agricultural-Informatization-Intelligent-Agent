"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { BigButton } from "@/components/BigButton";
import { UncontrolledFile } from "@/components/UncontrolledFile";

const LOCAL_DRAFT_KEY = "origin-field-note-draft";

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
  const [draftReady, setDraftReady] = useState(false);
  const [savedLocally, setSavedLocally] = useState(false);

  useEffect(() => {
    try {
      const requestedParcel = new URLSearchParams(window.location.search).get("parcel");
      const cached = window.localStorage.getItem(LOCAL_DRAFT_KEY);
      if (cached) {
        const saved = JSON.parse(cached);
        if (typeof saved.note === "string") setNote(saved.note);
        if (!requestedParcel && typeof saved.parcel === "string") setParcel(saved.parcel);
      }
      if (requestedParcel) setParcel(requestedParcel);
    } catch {
      // Private browsing can disable storage. Capture still works normally.
    } finally {
      setDraftReady(true);
    }
    api
      .today()
      .then((t) => {
        if (t.parcels?.length) setParcels(t.parcels);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!draftReady) return;
    try {
      window.localStorage.setItem(LOCAL_DRAFT_KEY, JSON.stringify({ note, parcel }));
      setSavedLocally(Boolean(note.trim()));
    } catch {
      setSavedLocally(false);
    }
  }, [draftReady, note, parcel]);

  async function toggleRecording() {
    if (holding) {
      rec.current?.stop();
      setHolding(false);
      return;
    }
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
      setErr("Microphone access is blocked. Type the field, product, rate, and buffer below instead.");
    }
  }

  async function send() {
    if (!note.trim() && !audio && !image) {
      setErr("Add a voice note, photo, or typed note first.");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const form = new FormData();
      form.set("parcel_id", parcel);
      form.set("note", note);
      if (audio) form.set("audio", audio, "voice.webm");
      if (image) form.set("image", image);
      const ev = await api.postEvent(form);
      try {
        window.localStorage.removeItem(LOCAL_DRAFT_KEY);
      } catch {
        // The server copy is authoritative once extraction succeeds.
      }
      setSavedLocally(false);
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
          <p className="eyebrow">Review before saving</p>
          <h1>Check the field record.</h1>
          <p className="muted">Gemini prepared this draft. Correct anything it misheard—you are the source of truth.</p>
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
          <h2>How Origin read this</h2>
          <p>
            <strong>{draft.provenance?.mode === "vertex" ? "Vertex AI" : "Deterministic fallback"}</strong>
            {draft.provenance?.model ? ` · ${draft.provenance.model}` : ""}
            {draft.provenance?.location ? ` · ${draft.provenance.location}` : ""}
          </p>
          <p className="muted">
            Extraction confidence: {Math.round((draft.confidence ?? 0) * 100)}%. Filter-strip compliance is
            checked by deterministic rules and shown before anything can be shared.
          </p>
        </section>
        {err && <p className="bad">{err}</p>}
        <div className="actions">
          <BigButton disabled={busy} onClick={confirm}>
            {busy ? "Saving…" : "Confirm field record"}
          </BigButton>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <p className="eyebrow">Field log</p>
        <h1>Record the work while it is fresh.</h1>
        <p className="muted">A voice note, label photo, or short typed note is enough. Saving a record never shares it.</p>
      </div>
      <div className="capture-grid">
        <section className="card capture-card">
          <p className="eyebrow">Fastest in the field</p>
          <h2>Say what you did</h2>
          <p className="muted">Tap once to start. Tap again when you are done.</p>
          <BigButton
            className={`big hold ${holding ? "rec" : ""}`}
            kind="ghost"
            aria-pressed={holding}
            onClick={toggleRecording}
          >
            {holding ? "Listening… tap to finish" : audio ? "Voice note ready · record again" : "Start voice note"}
          </BigButton>
          <label>Photograph the product label</label>
          <UncontrolledFile accept="image/*" capture="environment" onFile={setImage} />
          {(audio || image) && (
            <div className="input-status" aria-live="polite">
              {audio && <span>Voice note ready</span>}
              {image && <span>Photo ready</span>}
            </div>
          )}
        </section>
        <section className="card capture-card">
          <p className="eyebrow">Quiet option</p>
          <h2>Type a quick note</h2>
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
            placeholder="Ditch 40 — GreenGuard at 1.2 L/ha, with a 5 m strip by the watercourse."
          />
          {savedLocally && <p className="local-draft">Draft saved in this browser until it is sent.</p>}
          {err && <p className="bad">{err}</p>}
          <BigButton disabled={busy} onClick={send}>
            {busy ? "Reading the evidence…" : "Review this record"}
          </BigButton>
        </section>
      </div>
    </>
  );
}
