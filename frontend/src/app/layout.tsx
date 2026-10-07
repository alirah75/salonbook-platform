import type { Metadata } from "next";
import { connection } from "next/server";
import "@fontsource-variable/vazirmatn";
import "./globals.css";
import { AuthProvider } from "@/components/auth-provider";
import { ToastProvider } from "@/components/toast-provider";
import { Header, Footer } from "@/components/shell";

export const metadata: Metadata = {
  title: { default: "سالن‌بوک | زمانی برای خودت", template: "%s | سالن‌بوک" },
  description: "فضای شخصی شما برای ارتباط با سالن زیبایی.",
  robots: { index: false, follow: false },
};
export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Nonces require a fresh server render; static cached HTML cannot carry them.
  await connection();
  return (
    <html lang="fa" dir="rtl" data-scroll-behavior="smooth">
      <body>
        <AuthProvider>
          <ToastProvider>
            <a href="#main" className="skip-link">
              رفتن به محتوای اصلی
            </a>
            <Header />
            <main id="main" className="main-content">
              {children}
            </main>
            <Footer />
          </ToastProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
