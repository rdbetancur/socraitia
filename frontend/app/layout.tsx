import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Socraitia — AI Thinking Partner",
  description:
    "A thinking partner that questions your reasoning and builds a live knowledge graph of it.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
