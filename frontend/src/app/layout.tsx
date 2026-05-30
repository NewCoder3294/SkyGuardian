import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SkyGuardian — Operator Dashboard",
  description: "Local-frame map + intent controls. Offline-only.",
  applicationName: "SkyGuardian",
  icons: {
    icon: [
      { url: "/icon.png", type: "image/png" },
      { url: "/icon-512.png", type: "image/png", sizes: "512x512" },
    ],
    apple: [{ url: "/icon-512.png" }],
  },
};

export const viewport = {
  themeColor: "#f4f1e8",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text antialiased">{children}</body>
    </html>
  );
}
