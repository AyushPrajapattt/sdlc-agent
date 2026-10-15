import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Shell from "@/components/Shell";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Engineering Memory",
  description: "Evidence-grounded answers to “why is this code the way it is?”",
};

// Set the theme before first paint (stored choice, else system) to avoid a flash.
const themeInit = `try{var t=localStorage.getItem("wb-theme")||(matchMedia("(prefers-color-scheme: light)").matches?"light":"dark");document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="dark"}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`} data-theme="dark" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeInit }} /></head>
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
