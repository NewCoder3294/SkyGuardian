import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SkyGuardian — Operator Dashboard",
  description: "Local-frame map + intent controls. Offline-only.",
  applicationName: "SkyGuardian",
  icons: {
    icon: [{ url: "/icon.png", type: "image/png" }],
    apple: [{ url: "/icon.png" }],
  },
};

export const viewport = {
  themeColor: "#ffffff",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text antialiased">{children}</body>
    </html>
  );
}
