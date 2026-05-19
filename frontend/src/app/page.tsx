'use client'

import { Suspense } from 'react'
import { DashboardShell } from '@/components/layout/DashboardShell'
import { OverviewPage }   from '@/components/pages/OverviewPage'

export default function HomePage() {
  return (
    <DashboardShell>
      <Suspense fallback={<div className="animate-fade-up" style={{padding:'var(--space-8)',color:'var(--color-text-muted)'}}>Loading…</div>}>
        <OverviewPage />
      </Suspense>
    </DashboardShell>
  )
}
