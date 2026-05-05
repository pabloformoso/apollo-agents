import type { Metadata } from "next";
import "./globals.css";
import { PlayerProvider } from "@/lib/player";
import MiniPlayer from "@/components/MiniPlayer";

export const metadata: Metadata = {
  title: "ApolloAgents",
  description: "AI-powered DJ mix generator",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#0a0a0f] text-[#e2e2ff] font-mono antialiased pb-24">
        <PlayerProvider>
          {children}
          <MiniPlayer />
        </PlayerProvider>
      </body>
    </html>
  );
}
