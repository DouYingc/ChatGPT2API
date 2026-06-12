import type { Metadata, Viewport } from "next";
import { Toaster } from "sonner";
import "./globals.css";
import { PageTransition } from "@/components/page-transition";
import { RouteProgress } from "@/components/route-progress";
import { TopNav } from "@/components/top-nav";

export const metadata: Metadata = {
  title: "XY-AI HUB",
  description: "XY-AI HUB dashboard",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#fbfbfd",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="antialiased font-sans">
        <Toaster position="top-center" richColors offset={48} />
        <RouteProgress />
        <TopNav />
        <main className="h-screen overflow-x-hidden overflow-y-auto px-4 pt-12 pb-2 text-foreground [scrollbar-gutter:stable_both-edges] sm:px-6 sm:pt-14 lg:px-8">
          <div className="mx-auto box-border flex max-w-[1440px] flex-col pt-[env(safe-area-inset-top)]">
            <PageTransition>{children}</PageTransition>
          </div>
        </main>
      </body>
    </html>
  );
}
