import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgniNetra console",
  description:
    "Thermal source attribution over India. Displays precomputed phase 4 results.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
