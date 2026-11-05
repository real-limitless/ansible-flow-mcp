import type { ReactNode } from "react"

import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export function Surface({
  title,
  aside,
  children,
}: {
  title: string
  aside?: string
  children: ReactNode
}) {
  return (
    <Card>
      <CardHeader className="border-b">
        <CardTitle>{title}</CardTitle>
        {aside ? (
          <CardAction className="text-sm text-muted-foreground">
            {aside}
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
    </Card>
  )
}

export function PanelSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-24 w-full" />
    </div>
  )
}
