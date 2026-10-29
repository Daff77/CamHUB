# Design System Inspiration of CamHub

## 1. Visual Theme & Atmosphere
A quiet control room. The camera feeds are the only loud thing on screen; everything else is graphite and recedes. Status is carried by a dot and a plain sentence, not by badges, KPI cards or icon chips. Density is medium, corners are small, and there are no gradients or glows.

- Feeds get at least 70% of the viewport area; chrome is a 220px rail and a one-line header.
- One accent (amber) for focus and selection only. Green means live, grey means offline or unconfigured.
- Sentence case everywhere. No tracked-out caps eyebrows, no middle-dot meta strings.
- Technical metadata (IP, ID, port) is secondary: shown in a details line under the feed, never on top of the video.
- Borders only where they mean structure; depth comes from two surface steps.

## 2. Color Palette & Roles
| Role | Dark | Light |
|---|---|---|
| `--bg` page | `#1a1c1e` | `#f1efea` |
| `--panel` rail, tiles | `#222527` | `#fbfaf7` |
| `--raise` hover, buttons | `#2a2d30` | `#e8e5de` |
| `--line` dividers | `#34383b` | `#d8d4cb` |
| `--text` | `#ece9e3` | `#1f2123` |
| `--muted` | `#9b9e9a` | `#62655f` |
| `--live` connected | `#6fcf97` | `#1f7a4d` |
| `--accent` focus/selected | `#e9b44c` | `#9a6a00` |
| `--video` frame surround | `#0c0d0e` | `#0c0d0e` |
Shadows: `0 1px 0 rgb(0 0 0 / .25), 0 8px 24px -12px rgb(0 0 0 / .5)` on raised tiles only.

## 3. Typography Rules
Family: **Schibsted Grotesk**, fallback `system-ui, sans-serif`. Numbers use `tabular-nums`. No monospace except pasted URLs in Setup.
| Role | Size | Weight | Line height | Tracking |
|---|---|---|---|---|
| Page title | 28px | 600 | 1.15 | -0.02em |
| Status sentence | 15px | 400 | 1.4 | 0 |
| Tile title | 15px | 600 | 1.3 | -0.005em |
| Body / nav | 14px | 450 | 1.45 | 0 |
| Button | 13px | 550 | 1 | 0 |
| Caption / metadata | 12.5px | 400 | 1.4 | 0 |
| Micro (timestamp on feed) | 12px | 500 | 1 | 0.01em |

## 4. Component Stylings
- **Feed tile**: `--panel`, radius 8px, 1px `--line`. Video area uses `object-fit: contain` on `--video` (feeds are portrait composites, never crop). Title and status dot sit in an overlay bar at top with a dark scrim; details line sits below the video.
- **Buttons**: 32px high, radius 5px (8px tile − 3px inset), `--raise` fill, no border; hover lightens 4%; active `scale(.96)`; focus 2px `--accent` outline, 2px offset. Icon-only buttons have 40×40 hit area.
- **Status**: 8px dot + word ("Live", "Offline", "Not configured"). Offline tiles keep their size and show a plain message with one action.
- **Nav item**: 36px, radius 6px; selected = `--raise` fill + 2px `--accent` bar at left edge.
- **Unconfigured tile**: dashed 1px `--line`, no video area height collapse, single primary action "Set up protocol".

## 5. Layout Principles
Base unit 4px; scale 4/8/12/16/24/32/48. Rail 220px. Feed grid `repeat(auto-fit, minmax(340px, 1fr))`, gap 16px. Clicking a tile expands it to full row (focus mode); click again to restore. Radius scale: 5 (controls), 8 (tiles), 999 (dots).

## 6. Depth & Elevation
Two steps: page → panel. Raised state (hover tile) uses the shadow in section 2 and a `--line` lightening, no lift animation. Video frames get a 1px outline `oklch(1 0 0 / .1)`.

## 7. Do's and Don'ts
**Do**
- Keep feeds largest; collapse everything else.
- State connection status as a sentence in the header.
- Reveal Reload/Configure on hover and keyboard focus; always visible on touch.
- Use `text-wrap: balance` on titles.
- Respect `prefers-reduced-motion` and `prefers-color-scheme`.

**Don't**
- No KPI stat cards for counts that fit in a sentence.
- No ALL-CAPS tracked eyebrows or `A · B · C` meta strings on video.
- No gradient washes, glows, or icon chips in tinted squares.
- No `HTTP :8080 · MJPEG` overlays on the picture.
- No decorative entrance animations; only state-change feedback.

## 8. Responsive Behavior
Breakpoints 720px and 1080px. Under 720px the rail becomes a top bar with a horizontal camera switcher and tiles go single-column. Touch targets ≥44px; action buttons stay visible.

## 9. Agent Prompt Guide
Quick colors: bg `#1a1c1e`, panel `#222527`, text `#ece9e3`, live `#6fcf97`, accent `#e9b44c`.
- "Build a feed tile: 8px radius, video on `#0c0d0e` with contain, title overlay top-left, details caption underneath."
- "Write the header status as one sentence, e.g. ‘2 of 3 cameras connected. Checked 4:01 PM.’"
- Iteration: if it feels flat, adjust surface contrast by 2–3 lightness points; do not add borders or glows.
