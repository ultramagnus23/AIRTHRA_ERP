# Design

Source of truth: tokens originally extracted live from https://airthra.com (the parent brand's marketing site), then deliberately revised for the product surfaces per direct user direction (2026-08-14 revision): darker base, more rounded shape language, more assertive/upfront accent use, categorical color-coding for data-reporting screens. Still strictly the same four hues (rust/copper/moss/sand) plus neutrals - never introduce a color outside this palette, but use them more boldly than the marketing site does. Single theme, dark-first.

## Color strategy

**Committed**, not Restrained (revised up from the initial pass, per user feedback that Restrained read as "old"/lifeless for a data-reporting product). The accent hue (copper) now appears deliberately: category dots and top-edge accents on every data tile, brighter numerals, a background glow on entry screens. Still only the four Airthra hues - "more upfront color" means using rust/copper/moss more visibly, not adding new ones.

## Palette (OKLCH - revised from the parent-brand marketing values)

### Neutrals (surface layers, darkest to lightest)

| Token | Value | Use |
|---|---|---|
| `--color-bg` | `oklch(0.105 0.018 246)` | App background - deepened from the marketing site's lighter "abyss" for a richer, more modern all-day product base |
| `--color-panel` | `oklch(0.145 0.02 246)` | Cards, table rows, panels |
| `--color-midnight` | `oklch(0.195 0.024 246)` | Raised surfaces: modals, popovers, active nav item |
| `--color-hair` | `color-mix(in oklch, oklch(0.955 0.014 236) 8%, transparent)` | Hairline dividers |
| `--color-line` | `color-mix(in oklch, oklch(0.955 0.014 236) 16%, transparent)` | Borders, input outlines |
| `--color-mist` | `oklch(0.72 0.022 240)` | Secondary/muted text, placeholder, disabled |
| `--color-cloud` | `oklch(0.945 0.026 232)` | Tertiary highlight surface (rare) |
| `--color-fg` | `oklch(0.965 0.012 236)` | Primary text |

### Accent (single committed hue family - primary actions, selection, categorical coding)

| Token | Value | Use |
|---|---|---|
| `--color-rust` | `oklch(0.52 0.16 48)` | Primary button fill, active/selected state, critical alarm severity |
| `--color-copper` | `oklch(0.72 0.15 54)` | Category dots/top-edge accents on "process" data tiles, hover/lighter rust variant, warning severity, focus ring, sparkline stroke |

Both pushed more vivid (higher chroma) than the marketing-site originals - a product surface used all day needs the accent to read assertively in category dots and data call-outs, not recede the way it can on a hero page.

### Semantic + categorical (never arbitrary - always tied to a real meaning)

| Token | Value | Meaning |
|---|---|---|
| `--color-moss` | `oklch(0.64 0.1 152)` | Success/good/within-consent/approved, AND the categorical color for tank/inventory-level tiles |
| `--color-copper` | (shared with accent) | Warning/degraded/pending, AND the categorical color for process/emission-reading tiles |
| `--color-rust` | (shared with accent) | Error/critical/exceedance/rejected |
| `--color-sand` | `oklch(0.935 0.062 96)` | Rare warm highlight fill, used sparingly behind dark text, not as a text color |

**Categorical color-coding** (new): on data-dense screens, group related metrics by a consistent accent (e.g. emission/process readings = copper, inventory/tank levels = moss) via a small label dot + a 2px top-edge tint on the card. This is the "modern data reporting" pattern from dense industrial dashboards (grouped stat tiles, colored legend dots) - always tied to a real category, never decorative variety for its own sake.

**Purposeful glow**: a large, low-opacity (≈20-25%), heavily blurred radial glow in `--color-rust` may appear once per screen as ambient background context (e.g. behind the sign-in form) - not stamped on every panel, reserved for entry/empty-state moments.

Data-quality flags (raw sensor readings) remain a hard exception to all of the above: `--color-mist` text + the actual flag reason ("comm_error", "frozen", "out_of_range"), never hidden, never recolored to look "fine." Good readings use `--color-fg` (plain - "fine" should look boring even as everything else gets more colorful).

## Typography

Three families, each with one job. Never mix jobs.

- **`--font-display`: 'Fraunces', 'Times New Roman', serif** - page-level H1 only (e.g. "Fleet Health", "Bill of Materials"). Thin weight (300-400). Never in a button, table cell, badge, or form label. Product register discourages display fonts in UI - this is the one deliberate exception, used exactly once per screen.
- **`--font-body`: 'Archivo', 'Helvetica Neue', system-ui, sans-serif** - everything else: nav, buttons, labels, body copy, form controls, section headings (h2/h3, sans not serif).
- **`--font-mono`: 'IBM Plex Mono', ui-monospace, 'SF Mono', monospace** - every number, timestamp, ID, status code, currency figure, PO number. This is the instrument-panel read and should dominate the data-dense screens (sensor tiles, tables, KPI cards).

Fixed rem scale (product register - not fluid/clamp, this is desktop app UI):
`text-xs` 0.75rem · `text-sm` 0.875rem · `text-base` 1rem · `text-lg` 1.125rem · `text-xl` 1.375rem · `text-2xl` 1.75rem (display only) · `text-3xl` 2.25rem (display only, rare)

Uppercase wide-tracked mono labels (e.g. "STACK READING", section eyebrows) at `text-xs` with `letter-spacing: 0.15em` - a signature brand move from the parent site, reused for section kickers only.

## Shape language

**Rounded, not sharp** (reversed from the initial pass - the marketing site's `border-radius: 0` read as dated/old on product surfaces per direct user feedback, not modern).

- Buttons, inputs, badges: `rounded-lg` (8px).
- Small dividers/pills within a card (nav pill highlight, select): `rounded-lg`.
- Cards/panels: `rounded-2xl` (16px) - the dominant shape signature now.
- No nested cards. A table row is not a card.

## Elevation and glass

New in this revision - depth is now a first-class part of the system, not flat panels on flat background:

- **Shadow tokens** (`--shadow-sm/md/lg`, warm-tinted toward the abyss hue, not neutral black): every panel/tile carries at least `--shadow-sm`; the floating nav carries `--shadow-md`; true overlays would carry `--shadow-lg`.
- **`--shadow-glow`**: a copper-tinted glow ring, reserved for hover/focus states on interactive surfaces - not applied to static panels.
- **Glass is reserved for one thing**: the top nav, which is now detached/floating (inset with margin, not fused to the viewport edge) with `backdrop-blur-md` + `backdrop-saturate-150` over `--glass-bg`. This is the one deliberate glassmorphism moment in the app - purposeful floating chrome, not a default applied everywhere.

## Layout

- **Detached floating nav** (not full-bleed): sticky with a top/side inset, rounded-2xl, its own shadow - reads as chrome sitting above the content rather than fused to the browser edge.
- Predictable grids, standard table/form patterns per product register - the brand differentiates through color/type/depth, not through reinvented navigation.
- Generous but not padded-for-its-own-sake spacing; density is a feature on data-heavy screens (tables can run wide, sensor grids stay compact). Screens should be organized into clearly labeled sections (mono uppercase kicker + content), not one undifferentiated scroll.
- **More graph space**: data-dense screens should offer both a compact sparkline (per-tile, at-a-glance) AND at least one larger trend panel (dual-axis where relevant, with legend/gridlines/tooltip) - a data-reporting product earns more chart real estate than a generic admin CRUD screen.

## Components

- **Buttons**: primary = rust fill, fg text. Secondary = transparent, `--color-line` border, fg text. Destructive = rust border + rust text (not filled, reserve filled-rust for primary actions so severity doesn't compete with "the button you're supposed to click"). All states required: default/hover/focus/active/disabled/loading.
- **Data tiles**: `--shadow-sm`, `rounded-2xl`, a 2px categorical-accent top edge, a category dot beside the mono label, a value in `--font-mono`, an optional range/position bar (semantic-colored fill: moss in-range, copper near-edge, mist when flagged), an optional compact sparkline below.
- **Status badges**: `rounded-md`, colored by semantic token with a text label always present (never color-only) - green dot + "within consent", copper dot + "degraded", rust dot + "critical".
- **Tables**: `--color-panel` row background, `--color-hair` row dividers, mono for every numeric column, sans for every text column.
- **Forms**: `--color-line` border inputs on `--color-bg`, `rounded-lg`, `--color-copper` focus ring, mist placeholder text, fg input text.

## Motion

150-250ms transitions, `ease-out` curves (parent brand's `--ease-x: cubic-bezier(0.19, 1, 0.22, 1)` and `--ease: cubic-bezier(0.16, 1, 0.3, 1)`, reused directly). State changes only - no orchestrated load sequences, no decorative motion.
