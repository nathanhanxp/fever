"use client"

import { useRef, useEffect } from "react"
import { CameraControls } from "@react-three/drei"
import type { CodeUnitNode } from "@/types/graph"

/** Top-down map view: eye above the graph plane looking straight down. */
function computeTopDown(nodes: CodeUnitNode[]) {
  let minX = Infinity, minY = Infinity, minZ = Infinity
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
  for (const n of nodes) {
    if (n.x3d < minX) minX = n.x3d
    if (n.y3d < minY) minY = n.y3d
    if (n.z3d < minZ) minZ = n.z3d
    if (n.x3d > maxX) maxX = n.x3d
    if (n.y3d > maxY) maxY = n.y3d
    if (n.z3d > maxZ) maxZ = n.z3d
  }
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  const cz = (minZ + maxZ) / 2
  const spanX = Math.max(0.001, maxX - minX)
  const spanY = Math.max(0.001, maxY - minY)
  const spanZ = Math.max(0.001, maxZ - minZ)

  // Prefer looking down -Y→+Y (XZ plane). Fall back if that axis isn't the flat one.
  if (spanY <= spanX * 0.85 && spanY <= spanZ * 0.85) {
    const distance = Math.max(32, Math.max(spanX, spanZ) * 1.25)
    return {
      eye: [cx, cy + distance, cz] as [number, number, number],
      target: [cx, cy, cz] as [number, number, number],
    }
  }
  if (spanZ <= spanX * 0.85 && spanZ <= spanY * 0.85) {
    const distance = Math.max(32, Math.max(spanX, spanY) * 1.25)
    return {
      eye: [cx, cy, cz + distance] as [number, number, number],
      target: [cx, cy, cz] as [number, number, number],
    }
  }
  const distance = Math.max(32, Math.max(spanY, spanZ) * 1.25)
  return {
    eye: [cx + distance, cy, cz] as [number, number, number],
    target: [cx, cy, cz] as [number, number, number],
  }
}

export function CameraRig({ nodes, focusNodes }: { nodes: CodeUnitNode[]; focusNodes: CodeUnitNode[] | null }) {
  const controlsRef = useRef<CameraControls>(null)
  const framedFor = useRef(0)

  useEffect(() => {
    if (!controlsRef.current || nodes.length === 0) return
    // Frame once per graph size; don't re-home on every Play Step
    if (framedFor.current === nodes.length) return
    framedFor.current = nodes.length
    const f = computeTopDown(nodes)
    const timer = setTimeout(() => {
      const c = controlsRef.current
      if (!c) return
      c.setLookAt(f.eye[0], f.eye[1], f.eye[2], f.target[0], f.target[1], f.target[2], false)
    }, 50)
    return () => clearTimeout(timer)
  }, [nodes])

  useEffect(() => {
    if (!controlsRef.current) return
    if (!focusNodes || focusNodes.length === 0) return
    const f = computeTopDown(focusNodes)
    controlsRef.current.setLookAt(f.eye[0], f.eye[1], f.eye[2], f.target[0], f.target[1], f.target[2], true)
  }, [focusNodes])

  return (
    <CameraControls
      ref={controlsRef}
      smoothTime={0.45}
      minDistance={8}
      maxDistance={280}
      maxPolarAngle={Math.PI * 0.49}
      minPolarAngle={0.02}
    />
  )
}
