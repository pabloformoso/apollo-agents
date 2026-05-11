import type { Metadata } from "next";
import { DM_Sans, Instrument_Serif, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { PlayerProvider } from "@/lib/player";
import { ToastProvider } from "@/components/ember/feedback";

// Apollo v2.6.0 — Cinematic / Ember typography.
// Three Google Fonts loaded with next/font (self-hosted, zero CLS):
//   - Instrument Serif (italic display) — headings, hero copy, "voice".
//   - DM Sans                           — UI body, buttons, paragraphs.
//   - JetBrains Mono                    — uppercase labels, data, code.
// Exposed as CSS variables so Tailwind's font-display/sans/mono utilities
// resolve to them (see tailwind.config.ts).
const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif",
  display: "swap",
});
const dmSans = DM_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-dm-sans",
  display: "swap",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Apollo",
  description: "AI DJ — assemble, critique, perform.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`dark ${instrumentSerif.variable} ${dmSans.variable} ${jetbrainsMono.variable}`}
    >
      <body className="min-h-screen bg-ink text-ember-text font-sans antialiased">
        <PlayerProvider>{children}</PlayerProvider>
        <ToastProvider />
      </body>
    </html>
  );
}
