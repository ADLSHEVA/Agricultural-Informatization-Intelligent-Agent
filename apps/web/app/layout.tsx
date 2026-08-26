import type { Metadata } from "next";
import { Outfit } from "next/font/google";
import { Shell } from "@/components/Shell";
import "./globals.css";

const sans = Outfit({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Origin · Farmer-controlled AI agent",
  description: "Capture a farm fact once. Let a bounded AI agent share only what the farmer approved.",
  manifest: "/manifest.json",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={sans.variable}>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
