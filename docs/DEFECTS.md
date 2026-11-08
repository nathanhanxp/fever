# Graph defects confirmed in the running source

These were read off `frontend/src/Graph.tsx` and `frontend/src/graphView.ts` before the display fixes. Each one was in the code the app was serving.

| Id | Defect | Where |
| --- | --- | --- |
| a | `labelIds` was accepted and never read, so a hovered node did not gain a label. Labels were only clusters, or the focus node and its first hop, then cut at 14 with no overlap test. | `Graph.tsx` `NodeCloud` |
| b | `useLayoutEffect` copied every target into `cur.current` on each change, so the frame lerp started at the destination. Samples were stored by index, so a new node inherited another node's position. | `Graph.tsx` `NodeCloud` |
| c | `onPointerMissed` called `onSelect("")` for every missed pointer, including the end of an orbit drag. | `Graph.tsx` `GraphCanvas` |
| d | The canvas `key` included `Math.round(radius)`, so a small scene change remounted the canvas and reset the camera. | `Graph.tsx` `GraphCanvas` |
| e | Top-down placed the camera at `y + radius * 2.1` and `z + 0.01` with the default up vector, so the view sat on a near-parallel up axis. | `Graph.tsx` `GraphCanvas` |
| f | Sphere scales were fixed world units (`0.7 / 0.42 / 0.28`) and ignored scene radius and degree. | `Graph.tsx` `NodeCloud` |
| g | An aggregated edge was dashed when any member was unproved (`proved = cur.proved && e.proved`). The badge did not say how many members were proved. | `graphView.ts` edge grouping |
| h | Parallel copies were offset on Y only, so they stacked in the top-down view. | `Graph.tsx` `Edges` |
| i | Edges had no arrow. | `Graph.tsx` `Edges` |
| j | The instance mesh count was `min(length, 2048)`, so later nodes were dropped. | `Graph.tsx` `NodeCloud` |
| k | An expanded cluster used `0.85 * sqrt(i)` around the centroid, and `separate()` only pushed on x/z. Neighbors were not moved out, and other clusters were not dimmed. | `graphView.ts` `buildScene` |
| l | `placeNodes` used `n.z \|\| n.y` when top-down positions were missing, which mixed axes. | `graphView.ts` `placeNodes` |

Other product gaps visible in the same build: the right pane stacked the step, the node, the ripple, ask, a second dependency filter, weights, and the brief in one scroll. Agent durations were percentage shares of elapsed time with token count 0. The PDF writer emitted truncated Helvetica lines. Upload was not implemented. The analyzer root was a constant.

Screenshots of those states were not saved as image files in this pass. The fixes that follow were checked by typecheck and by loading the app.
