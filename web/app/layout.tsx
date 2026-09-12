import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "UniTime AI Smart Ingestion Gateway",
  description:
    "Production AI Ingestion & Semantic Validation Interface for UniTime Academic Timetabling.",
  icons: {
    icon: "/favicon.ico",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f172a",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans min-h-screen flex flex-col bg-background text-foreground antialiased`}
      >
        <div className="flex-1 flex flex-col">{children}</div>

        <Toaster
          position="bottom-right"
          richColors
          closeButton
          theme="system"
        />
      </body>
    </html>
  );
}
