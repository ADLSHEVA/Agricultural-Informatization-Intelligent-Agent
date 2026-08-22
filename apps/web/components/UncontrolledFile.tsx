"use client";

import { useEffect, useRef } from "react";

/** File input that React never reconciles. React 19 flips a normal
 *  `<input type="file">` from uncontrolled to controlled on parent updates. */
export function UncontrolledFile({
  id,
  accept,
  capture,
  onFile,
}: {
  id?: string;
  accept?: string;
  capture?: string;
  onFile: (file: File | null) => void;
}) {
  const host = useRef<HTMLSpanElement>(null);
  const onFileRef = useRef(onFile);
  onFileRef.current = onFile;

  useEffect(() => {
    const input = document.createElement("input");
    input.type = "file";
    if (id) input.id = id;
    if (accept) input.accept = accept;
    if (capture) input.setAttribute("capture", capture);
    input.onchange = () => onFileRef.current(input.files?.[0] ?? null);
    host.current?.replaceChildren(input);
    return () => {
      input.onchange = null;
      input.remove();
    };
  }, [id, accept, capture]);

  return <span ref={host} />;
}
