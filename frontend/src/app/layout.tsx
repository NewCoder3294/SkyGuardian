import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SkyGuardian - Persistent Situational Awareness",
  description:
    "Autonomous aerial teammates for persistent situational awareness across sea, land, and air missions.",
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
  width: "device-width",
  initialScale: 1,
  themeColor: "#f6f3ea",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text antialiased">{children}</body>
    </html>
  );
}
