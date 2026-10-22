import type { ReactNode } from 'react'

type AppLayoutProps = {
  header: ReactNode
  children: ReactNode
}

export function AppLayout({ header, children }: AppLayoutProps) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {header}
      <main className="bc-app-main min-w-0 w-full pb-6">{children}</main>
    </div>
  )
}
