import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgniNetra research console",
  description:
    "What is burning over India, and how sure the model is: thermal source attribution from satellite detections.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
