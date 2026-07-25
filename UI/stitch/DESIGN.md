---
name: LabLens Design System
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#444839'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#757967'
  outline-variant: '#c5c9b4'
  surface-tint: '#4d6700'
  primary: '#4d6700'
  on-primary: '#ffffff'
  primary-container: '#a7c957'
  on-primary-container: '#3d5300'
  inverse-primary: '#b0d360'
  secondary: '#67587d'
  on-secondary: '#ffffff'
  secondary-container: '#e6d2fe'
  on-secondary-container: '#68587d'
  tertiary: '#615f4b'
  on-tertiary: '#ffffff'
  tertiary-container: '#c1bea6'
  on-tertiary-container: '#4e4d3a'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ccf078'
  primary-fixed-dim: '#b0d360'
  on-primary-fixed: '#151f00'
  on-primary-fixed-variant: '#394d00'
  secondary-fixed: '#eddcff'
  secondary-fixed-dim: '#d2bfea'
  on-secondary-fixed: '#221536'
  on-secondary-fixed-variant: '#4f4064'
  tertiary-fixed: '#e7e3ca'
  tertiary-fixed-dim: '#cac7af'
  on-tertiary-fixed: '#1d1c0d'
  on-tertiary-fixed-variant: '#494835'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
typography:
  display-lg:
    fontFamily: Manrope
    fontSize: 48px
    fontWeight: '800'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Manrope
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
  headline-md:
    fontFamily: Manrope
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-sm:
    fontFamily: Manrope
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Manrope
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Manrope
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Manrope
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.05em
  label-sm:
    fontFamily: Manrope
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
  headline-lg-mobile:
    fontFamily: Manrope
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  container-margin: 20px
  gutter: 16px
---

## Brand & Style

The design system is rooted in the "Modern Healthcare" aesthetic, blending **Corporate Modern** reliability with a **Tactile** softness. It aims to evoke feelings of calm, precision, and clarity—essential for users interpreting medical data. 

The visual language utilizes a "Soft-Brutalist" approach: structural layouts and clear scanning zones are softened with pastel hues and rounded corners. The interface avoids clinical sterility by using a warm, natural palette, ensuring the user feels supported rather than overwhelmed by information. 

**Core Tenets:**
- **Clarity over Decoration:** Every element serves a functional purpose in data scanning or interpretation.
- **Organic Precision:** Geometric layouts are tempered with organic, soft-edged containers.
- **Trustworthy Intelligence:** Professional typography paired with a serene color palette to convey AI-driven accuracy.

## Colors

The palette is derived from natural, soothing tones that differentiate health status without inducing "medical anxiety."

- **Primary (Sage Green):** Used for growth, positive health outcomes, and primary actions like "Scan" or "Analysis."
- **Secondary (Pale Lavender):** Reserved for status indicators, "State of Health" summaries, and auxiliary actions like "Share."
- **Tertiary (Cream Yellow):** Acts as a highlighting agent for filters, search bars, and chat interfaces to draw focus without high-contrast strain.
- **Neutrals:** A range of warm grays and off-whites are used for surface backgrounds to maintain a soft, paper-like quality.

## Typography

**Manrope** is the sole typeface for this design system. Its modern, geometric construction offers the technical precision required for laboratory data while its open apertures ensure high legibility in dense document lists.

- **Headlines:** Use Bold (700) or ExtraBold (800) for clear hierarchy in scan results.
- **Labels:** Small caps or increased letter spacing are used for metadata (e.g., "DATE / DROP_DOWN") to distinguish from primary content.
- **Body:** Regular (400) is used for all medical descriptions and terms/conditions to ensure a comfortable reading experience.

## Layout & Spacing

The layout utilizes a **Fluid Grid** for mobile-first utility, transitioning to a structured **8-column grid** for tablet/desktop analysis views. 

- **Scanning Focus:** The "Scan" zone on the home screen occupies the largest visual real estate, using a 1:1 aspect ratio container.
- **Card Spacing:** Document cards use an 8px vertical gap to maintain a list-like feel while allowing individual interaction zones.
- **Safe Areas:** All screens maintain a 20px side margin to ensure content doesn't hit the bezel edges, especially on curved mobile displays.

## Elevation & Depth

Hierarchy is established through **Tonal Layers** and **Low-Contrast Outlines** rather than heavy shadows, maintaining the "clean" medical aesthetic.

- **Level 0 (Background):** Primary neutral color (#F8F9FA).
- **Level 1 (Cards/Containers):** Pure white surfaces with a 1px solid border in a slightly darker neutral or the primary green.
- **Level 2 (Interactive/Floating):** Use of subtle ambient shadows (0px 4px 12px, 5% opacity) only for floating action buttons or active modals.
- **Glassmorphism:** Navigation drawers and overlay filters use a backdrop blur (12px) to maintain context with the scanning interface underneath.

## Shapes

The system uses **Rounded (0.5rem)** as the baseline for all functional components. This softens the "industrial" nature of healthcare data.

- **Primary Containers:** 1rem (rounded-lg) for main cards and the scan viewport.
- **Action Buttons:** 0.5rem (base) for a sturdy, professional feel.
- **Status Chips:** Full-pill (3rem) for health status indicators to differentiate them from actionable buttons.

## Components

### Buttons & Chips
- **Primary Action (Scan):** Large, Sage Green background with white bold text. High tap target (min 56px height).
- **Secondary Action (Share/Download):** Lavender background, using `label-md` typography.
- **Filter Chips:** Cream Yellow with a subtle border; indicates active selection through a slight darkening of the fill.

### Document Cards
Cards are horizontally oriented. The left 70% contains the metadata (Name, Date), while the right 30% is a vertical stack of Lavender/Blue-tinted action buttons (Share/Download). This creates a clear "Identify then Act" user flow.

### Data Visualization
- **Health Analysis Blocks:** Large, Sage Green containers with high-contrast text for "WHO Comparison" data.
- **Graphs:** Use clean, thin lines with circular data points. Avoid fills under the line to keep the interface airy.

### Input Fields
- **Chat/Search:** Cream Yellow backgrounds with rounded corners and centered placeholder text for an inviting, conversational feel.
- **Document Scanners:** The viewfinder should have 2px thick "corner brackets" in the primary green to guide the user's eye.