import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'NexusTrader — Dashboard',
  description: 'Production-grade algorithmic trading dashboard',
  icons: { icon: '/favicon.ico' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="color-scheme" content="dark" />
      </head>
      <body>{children}</body>
    </html>
  );
}
