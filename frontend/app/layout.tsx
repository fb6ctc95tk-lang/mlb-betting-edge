import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MLB Betting Edge",
  description: "Today's MLB games dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
