import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SkopaqTrader",
  description: "India's first self-evolving AI trading platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 min-h-screen">
        <nav className="border-b border-gray-800 px-6 py-4">
          <div className="max-w-6xl mx-auto flex items-center justify-between">
            <h1 className="text-xl font-bold tracking-tight">
              Skopaq<span className="text-blue-400">Trader</span>
            </h1>
            <span className="text-xs text-gray-500">v0.1.0</span>
          </div>
        </nav>
        <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
