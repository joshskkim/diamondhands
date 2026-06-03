import type { Metadata } from "next";
import { Inter, Space_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { SiteNav } from "@/components/site-nav";

// Body text — Inter is exceptionally legible at small sizes / in dense tables.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

// Display / headings — Space Grotesk gives titles a sharp, modern data feel.
const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  display: "swap",
});

// Numbers — JetBrains Mono has clean tabular figures for stat columns.
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Diamond — MLB Projections",
    template: "%s · Diamond",
  },
  description: "Stats-first MLB batter projections",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-[#08090d] text-zinc-100">
        <Providers>
          <SiteNav />
          {children}
        </Providers>
      </body>
    </html>
  );
}
