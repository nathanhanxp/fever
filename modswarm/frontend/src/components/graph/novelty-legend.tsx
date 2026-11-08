"use client"

/** Tiny legend — judges need colors, not essays. */
export function NoveltyLegend({ live }: { live?: boolean }) {
  return (
    <div className="absolute bottom-4 left-3 z-10 pointer-events-none max-w-[220px]">
      <div className="rounded-md border bg-background/90 backdrop-blur px-2 py-1.5 text-[10px] space-y-0.5 shadow-sm">
        <p><span className="text-red-500">●</span> legacy vuln (measured)</p>
        <p className={live ? "" : "text-muted-foreground"}>
          <span className={`text-orange-500 ${live ? "animate-pulse" : ""}`}>●</span> predicted API risk{live ? " · live" : " · on Play"}
        </p>
        <p className={live ? "" : "text-muted-foreground"}>
          <span className={`text-purple-500 ${live ? "animate-pulse" : ""}`}>●</span> predicted transit{live ? " · live" : " · on Play"}
        </p>
        <p className="text-muted-foreground">sky = cut · orange/purple = predicted risk · click to audit</p>
      </div>
    </div>
  )
}
