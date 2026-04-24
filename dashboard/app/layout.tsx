import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "jarvis — paper trading",
  description: "Gemini-driven paper trading agent on Hyperliquid",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
