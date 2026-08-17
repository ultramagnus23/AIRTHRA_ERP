# Product

## Register

product

## Users

Three distinct groups, all authenticated, all task-focused:

- **Plant operators** (tenant_read): staff at a client's chemical plant checking live sensor readings, acknowledging alarms, logging maintenance/lab-sample events, and reviewing compliance data. Likely on a shared control-room monitor or a desk browser, checking in periodically through a shift, not constantly staring at it.
- **Airthra ops/admin staff** (global_admin/global_read): internal team monitoring fleet health across all client plants, triaging alarms, reviewing risk scores, approving invoices, running compliance exports. Desk-based, full workday use, cross-plant comparison is the core task.
- **Airthra ERP/procurement staff** (global_admin/global_read): internal team running vendors, POs, BOMs, GRN, inventory genealogy, fabrication jobs. Heavy form-filling and data-table work, full workday use.

Drivers (unauthenticated, token-linked) use one narrow mobile page to start/stop a delivery trip - not part of the main product surface.

## Product Purpose

Airthra Research sells Flue Gas Desulfurization as infrastructure, not equipment: a plant never buys the scrubber, Airthra owns and operates it, and gets paid on SO2 actually captured. This platform is the operational nervous system for that business: real-time sensor telemetry from Raspberry Pi units at each plant, compliance/billing built on that raw data, and the ERP (vendors through fabrication through installation) that builds and maintains the physical units. Success looks like: an operator trusts a flagged reading is genuinely flagged (never hidden), an admin can tell in one glance which of 50 plants needs attention, and an ERP user can trace any component back to its vendor without leaving the screen.

## Brand Personality

Precise, trustworthy, industrial - and detailed, modern. This is safety- and billing-relevant instrumentation data, not a consumer app: calm, data-dense, confident, no decoration for its own sake. The parent brand (airthra.com) reads as an editorial, technically fluent, unapologetically dark mining/industrial identity ("mining the sky, fueling the earth") - precise formulas, live data tickers, monospace timestamps, thin-weight serif headlines. The product surfaces should feel like the instrument panel version of that same company, not a generic SaaS reskin of it.

## Anti-references

Not generic light-grey admin-template SaaS (the look this codebase currently has - default Tailwind slate-on-white, ad hoc per-section accent colors with no shared system). Not a "friendly consumer" warm-cream aesthetic (the two mockups the user referenced for craft-quality inspiration - Crextio, SugarCRM - are explicitly NOT to be followed for color, only for spacing/card polish/typographic confidence). Not decorative: no gradients, no glassmorphism, no side-stripe accent borders, no gradient text.

## Design Principles

1. **One brand, one palette.** Every screen (client dashboard, admin console, ERP, driver page) draws from the exact same Airthra token set (abyss/midnight/panel neutrals, rust/copper/moss/sand accents) - no section invents its own accent color.
2. **Raw data is sacred, visually.** A flagged sensor reading must always look flagged - distinct, legible, honest - never softened into looking "fine." This is a platform rule, not a style preference.
3. **Mono for data, sans for interface, serif for arrival.** IBM Plex Mono renders every number/timestamp/ID (the instrument-panel read), Archivo carries all UI chrome (nav, buttons, labels, forms), Fraunces appears only at page-level title moments - never in a button, a table cell, or a data label.
4. **Density with hierarchy.** These are power-user tools used all day; don't pad them into a marketing page. Structure through spacing rhythm and type weight, not through wrapping everything in a card.
5. **Familiar over novel.** Standard nav, standard tables, standard forms. The brand differentiates through color/type/craft, not through reinvented interaction patterns.

## Accessibility & Inclusion

WCAG AA contrast minimum on the dark base (the real Airthra token set is chosen with enough lightness separation to support this - verify each new color pairing, don't assume). Never convey a data-quality flag, alarm severity, or status by color alone - pair with text/icon. Standard keyboard navigation and focus states on every interactive element (forms are a major daily workload for ERP/procurement staff).
