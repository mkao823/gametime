import type { Metadata } from "next";
import { AppShell } from "@/components/AppShell";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: {
    default: "gametime",
    template: "%s | gametime",
  },
  description: "MLB pregame ensemble predictions — research dashboard.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
