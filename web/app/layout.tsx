import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stock Advisor — Community",
  description: "Follow investors, compare verified track records, and talk tickers.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
