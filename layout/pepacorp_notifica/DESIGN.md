---
name: PEPACORP NOTIFICA
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#5c3f40'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#906f70'
  outline-variant: '#e5bdbe'
  surface-tint: '#be0037'
  primary: '#b80035'
  on-primary: '#ffffff'
  primary-container: '#e11d48'
  on-primary-container: '#fffaf9'
  inverse-primary: '#ffb3b6'
  secondary: '#565e74'
  on-secondary: '#ffffff'
  secondary-container: '#dae2fd'
  on-secondary-container: '#5c647a'
  tertiary: '#585c5d'
  on-tertiary: '#ffffff'
  tertiary-container: '#717476'
  on-tertiary-container: '#f9fbfd'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffdada'
  primary-fixed-dim: '#ffb3b6'
  on-primary-fixed: '#40000c'
  on-primary-fixed-variant: '#920028'
  secondary-fixed: '#dae2fd'
  secondary-fixed-dim: '#bec6e0'
  on-secondary-fixed: '#131b2e'
  on-secondary-fixed-variant: '#3f465c'
  tertiary-fixed: '#e0e3e5'
  tertiary-fixed-dim: '#c4c7c9'
  on-tertiary-fixed: '#191c1e'
  on-tertiary-fixed-variant: '#444749'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  headline-xl:
    fontFamily: Hanken Grotesk
    fontSize: 56px
    fontWeight: '800'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 32px
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 28px
    fontWeight: '700'
    lineHeight: '1.2'
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: '1.0'
    letterSpacing: 0.08em
  button-text:
    fontFamily: Hanken Grotesk
    fontSize: 14px
    fontWeight: '700'
    lineHeight: '1.0'
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  container-padding-desktop: 80px
  container-padding-mobile: 24px
  gutter: 24px
  section-gap: 48px
  input-padding: 16px
---

## Brand & Style
This design system is built for a high-stakes corporate notification and management environment. The brand personality is authoritative, precise, and urgent, reflecting a "command and control" aesthetic that ensures critical information is never missed.

The visual style is **Corporate / Modern** with a lean toward **High-Contrast Boldness**. It utilizes a stark split-screen layout—as seen in the reference—to create a functional hierarchy between narrative branding and interactive utility. The aesthetic relies on extreme clarity, heavy typographic weight, and a disciplined use of its signature red to signal importance and action. It is designed to evoke a sense of security, high performance, and institutional reliability.

## Colors
The palette is dominated by a high-contrast triad of Deep Red, Stark White, and Slate Black. 

- **Primary (#E11D48):** Used exclusively for primary actions, critical alerts, and brand accents. It provides the necessary "pulse" for a notification-centric system.
- **Secondary / Neutrals:** Deep slate and black are used for text and high-contrast backgrounds (such as the left-side brand panel). 
- **Surface Colors:** A crisp white is the primary background for data entry and reading, while a very light grey (#F1F5F9) is used for input fills and subtle containers to maintain depth without sacrificing the clean, professional look.

## Typography
The typography strategy uses **Hanken Grotesk** for headlines to provide a sharp, contemporary, and engineered feel. **Inter** is used for body text and UI labels to ensure maximum legibility at smaller scales.

Key typographic rules:
- **Headlines:** Use tight tracking and heavy weights (Bold/ExtraBold).
- **Labels:** Small caps with increased letter spacing are used for form headers to create a "technical" look.
- **Contrast:** High contrast between headline sizes and body text is essential to mirror the professional editorial style of the reference.

## Layout & Spacing
The layout follows a **Fixed-Fluid Hybrid** model. Large desktop views utilize a split-screen (50/50 or 60/40) composition. 

- **The Left Panel:** Fixed brand/narrative space with dark background. Content is centered or bottom-aligned.
- **The Right Panel:** Fluid scrollable area for forms, data, and notifications. 
- **Grid:** A 12-column grid is used within the main content containers.
- **Mobile Reflow:** On mobile, the left brand panel collapses into a simplified top header or is hidden in favor of the primary action area, with padding reduced to 24px for optimal screen utility.

## Elevation & Depth
In line with the professional corporate aesthetic, this design system uses **Tonal Layers** and **Low-Contrast Outlines** instead of heavy shadows.

- **Flatness:** UI elements generally sit flat on the surface.
- **Depth via Fill:** Containers (like input fields) use a subtle light-grey fill to distinguish themselves from the white background.
- **Interaction Elevation:** A very subtle, highly diffused shadow (10% opacity black, 8px blur) may be used only on active floating elements like dropdowns or toast notifications to separate them from the base UI layer.

## Shapes
The shape language is **Rounded**, striking a balance between modern friendliness and corporate precision.

- **Standard Elements:** Buttons and Input fields use a 0.5rem (8px) corner radius.
- **Small Elements:** Chips and tags use a pill-shape for distinct visual categorization.
- **Large Containers:** Cards or modal windows use a 1rem (16px) radius to feel substantial and modern.

## Components

### Buttons
- **Primary:** Solid Black or Red background, white uppercase text, center-aligned with an optional trailing icon (arrow).
- **Secondary:** Outlined with a 1px border, using the primary brand color for text and border.

### Input Fields
- **Styling:** Light grey fill (#F1F5F9) with a 1px border that darkens on focus.
- **Labels:** Positioned above the field in uppercase bold Inter (11px).
- **Validation:** Error states use the primary red (#E11D48) for borders and helper text.

### Cards & Notifications
- **Notification Cards:** White background with a thick 4px left-border accent in Primary Red to denote "Unread" or "Urgent" status.
- **Lists:** Clean, border-bottom separated rows with high-contrast typography for titles and muted slate for metadata.

### Chips & Badges
- **Status Indicators:** Small, pill-shaped badges with low-opacity background tints of the status color (e.g., light red tint for "Critical").