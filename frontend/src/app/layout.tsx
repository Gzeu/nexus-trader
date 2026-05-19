import type { Metadata, Viewport } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Nexus Trader — Algorithmic Trading Dashboard',
  description: 'Production-grade algorithmic trading dashboard with TradingView integration',
  icons: {
    icon: '/favicon.svg',
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#0f0e0d',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function(){
                var t=localStorage.getItem('nt-theme')||'dark';
                document.documentElement.setAttribute('data-theme',t);
              })()
            `,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  )
}
