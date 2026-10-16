---
name: ideology-app
description: Neutral, civic, mobile-first voting advice tool. Calm and trustworthy; no party colours in the base UI.
designAssets:
  sourceOfTruth: []
  generatedConcepts: []
colors:
  primary: "#2F4B7C"
  secondary: "#5B6B82"
  accent: "#E0A526"
  background: "#F7F7F5"
  surface: "#FFFFFF"
  text: "#1D2330"
  muted: "#6B7280"
  border: "#E3E3DE"
  scale-disagree-strong: "#8A8F98"
  scale-agree-strong: "#2F4B7C"
typography:
  h1:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 28px
    fontWeight: 700
  h2:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 20px
    fontWeight: 600
  body:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 16px
  quote:
    fontFamily: "Georgia, serif"
    fontSize: 15px
rounded:
  sm: 6px
  md: 12px
spacing:
  sm: 8px
  md: 16px
  lg: 24px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.md}"
  scale-option:
    minHeight: 48px
    rounded: "{rounded.md}"
---

# Design Direction

## Overview

A calm, civic tool. The UI must never suggest a preference: identical treatment for every party, and no party colours outside their logos.

## Existing Design Assets

None. This file is the initial direction.

## Generated Concept Images

None yet.

## Product Feel

Trustworthy, quiet, readable, like a good public-service website. Evidence (quotes) is a first-class element, not hidden detail.

## Colors

A neutral blue-grey base. The amber accent is reserved for the Important flag and focus states. The 5-point scale uses a neutral grey-to-blue ramp, never red/green (that reads as "wrong/right").

## Typography

Inter for the UI; a serif for Evidence quotes so they read as source material.

## Layout

A single column on mobile (16px gutter), up to a 720px reading width on desktop. One Statement per screen in the Questionnaire, with a progress bar.

## Shapes

Soft 12px radius on cards and scale options; 48px minimum tap targets.

## Components

- **Statement card**: the statement text, a 5-option scale, a "skip" link, and an Important toggle (a star).
- **Ranking row**: party logo + name, percentage bar, and a "low coverage" badge when it applies.
- **Breakdown row**: the Statement, the user's answer, and each party's position as an expandable item that reveals the Evidence quote + source link.
- **Share button**: copies the Share Link; a short note explains that nothing is stored.

## Core Screens

1. Landing: choose an Election, a short methodology summary, and an "AI-generated" disclosure.
2. Questionnaire.
3. Results: ranking + per-Statement breakdown + share.
4. Methodology: how Statements and Positions are generated and validated.

## Responsive Baseline

Mobile-first; the breakdown becomes a table only at ≥ 900px.

## Accessibility Baseline

WCAG 2.1 AA contrast; the scale can be used by keyboard and screen reader (radio group); the meaning of the scale never relies on colour alone.

## Do's and Don'ts

- Do show party order by score only; ties are ordered alphabetically.
- Do label AI-generated content clearly.
- Don't use party colours for bars or backgrounds.
- Don't use red/green on the agreement scale.

## Open Design Questions

- Logo and product name.
- Whether to show party logos at all (licensing and neutrality).
