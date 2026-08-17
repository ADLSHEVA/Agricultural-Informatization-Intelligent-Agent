"use client";

import type { ButtonHTMLAttributes } from "react";

export function BigButton({
  kind = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "ghost" | "danger" }) {
  return <button className={`big ${kind} ${className}`.trim()} {...props} />;
}
