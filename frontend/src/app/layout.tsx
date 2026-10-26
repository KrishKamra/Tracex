import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import "@xyflow/react/dist/style.css";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Tracex — Context-Adaptive Workspace",
  description: "AST-aware hybrid code search: BM25, dense embeddings and call graph, fused by weighted RRF.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// Applied before first paint so a saved light theme never flashes dark.
const themeScript = `try{var t=localStorage.getItem("tracex-theme");document.documentElement.dataset.theme=t==="light"?"light":"dark"}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" className={`${inter.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="font-sans text-[13px]">{children}</body>
    </html>
  );
}
