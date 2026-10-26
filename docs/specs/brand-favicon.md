# Spec: brand-favicon

## Goal

The browser tab shows the IdeologiApp logo as its icon and `IdeologiApp` as its title (user request, 2026-10-26). Settles the risks entry "Browser tab title and favicon".

## Decisions

- **Tab icon:** the product logo SVG (`apps/web/src/assets/ideologiapp-logo.svg`) is linked as `<link rel="icon" type="image/svg+xml">` in `apps/web/index.html`. Vite fingerprints it into `/assets/`, so it is same-origin and cached like every asset. It reads well down to 16px (checked visually). A `favicon.ico` fallback (16/32/48px, transparent corners) is also added in `apps/web/public/`, which Vite copies to the dist root: the browser walk showed `/favicon.ico` still being requested (by browser chrome outside the page) and answering 404.
- **Home-screen icon:** `apps/web/src/assets/ideologiapp-touch-icon.png`, 180x180, opaque. It is the logo rendered once (macOS Quick Look, then Pillow in a throwaway environment) with the sky-blue background filled to the corners, because iOS shows transparent corners as black. No new dependency.
- **Titles (user decision):** `<title>IdeologiApp</title>`; Methodology and shared result titles become `Metodología · IdeologiApp` and `Resultado compartido · IdeologiApp`. The Landing subtitle text is unchanged.
- **Out of scope:** a web app manifest, maskable/Android icons, theme-color.

## Acceptance

- `apps/web/index.html` declares exactly one SVG icon link and one apple-touch-icon link, both same-origin, and the title `IdeologiApp` (Vitest `src/app/index-html.test.tsx`).
- The built `dist/index.html` points both links at fingerprinted `/assets/` files.
- Methodology and shared-result titles updated; tests updated.
- `./init.sh` passes.
- Browser check at 375px and desktop, light and dark: the tab shows the logo and title on the Landing, Methodology and shared result; `/favicon.ico` answers 200 with the logo; no console errors; only same-origin requests.
