# Latest refinement — white-dominant workspace

The latest user request swaps white and black and permits supporting colors. Current target is approximately 60% white, 30% black, 10% fresh mint. White reading surfaces and a light neutral workspace are balanced by the dark navigation and Canvas2D orb panel. Muted text, fine neutral separators and restrained warning/error colors improve hierarchy and state recognition. Mint remains the principal accent. Percentages are visual guidance across responsive layouts.

Preserved 44px primary controls, visible keyboard focus, source citation navigation, reduced motion and animation pause. Softened high-contrast borders and hover inversions, restored readable secondary text, used semantic warning/error colors with existing explicit labels, and limited shadows to document depth and overlays. The regenerated offline preview contains only synthetic fixtures.

Validation: three contrast/markup/preview checks and the UI behavior checks passed. Canvas JavaScript syntax passed. Actual visual browser verification and deployment remain pending.

---

# Current palette correction

The latest user instruction supersedes the white-dominant brief below. The UI now uses exactly three authored colors: black #000000 (60% visual emphasis), white #FFFFFF (30%) and fresh mint #A8F0CE (10%). Black covers the workspace shell, navigation, overview and animation panel; white covers evidence and reading panels; mint emphasizes actions and selection. Responsive proportions are visual guidance, not a measured pixel quota.

Removed colored warnings, gray neutrals, tinted surfaces and colored shadows from all loaded stylesheets. Status meaning remains explicit in words, border styles and emphasis. Canvas ribbons use the same three colors with projection and alpha for depth; antialiasing naturally blends pixels. Preview regenerated. Four palette/markup checks, UI behavior checks and Canvas scheduling checks passed. Actual browser visual inspection remains pending; no deployment performed.

---

Historical design record follows.

# PolicyPilot review interface

Design brief, 18 November 2026. User requested a white 60%, onyx black 30%, fresh mint 10% redesign, with UI/UX research and implementation. This supersedes the earlier dark graphite palette. Percentages describe approximate visual emphasis across the desktop workspace, not exact pixel quotas at every breakpoint.

## Direction and scope

An evidence-first product workspace for a human claims reviewer. White reading surfaces, an onyx navigation rail and sculptural Canvas2D orb panel, mint primary actions and selected states. A restrained editorial heading and system sans-serif interface keep the existing app fast and self-contained. Retain existing vanilla HTML/CSS/JS, API contracts, authentication and source citations. Do not add external font requests, a framework, WebGL, fabricated production results, GPU calls or inference dependencies.

A fully white layout would weaken the requested onyx presence. A fully dark dashboard would contradict the new brief. The selected mixed workspace uses onyx for navigation and the overview illustration, and white for all prolonged reading. On mobile, prioritize reading and usable controls over matching a precise color ratio.

## Research translated into decisions

- W3C WCAG 2.2 contrast minimum: ordinary text needs 4.5:1; large text 3:1. Use onyx #181C1A and secondary #56625C on white; mint #A8F0CE always carries dark text. Use dark green #245C45 for text links on white. https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
- W3C target size minimum: 24 CSS pixels with defined exceptions. Use at least 44px for primary controls and 32px for compact secondary actions; use larger whole-row targets. https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
- W3C focus not obscured: keep keyboard focus visible, avoid sticky overlays, match DOM and visual reading order, and preserve source-page focus after a citation click. https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html
- NN/g progressive disclosure: keep field values visible, expand conflicting evidence by default, show detailed source quotes on demand, and keep operational settings in the existing secondary dialog. https://www.nngroup.com/articles/progressive-disclosure/
- NN/g visibility of system status: show the actual service state; distinguish processing, missing evidence, errors and disconnected services with text, not color alone. https://www.nngroup.com/articles/visibility-system-status/
- GOV.UK error messages: explain failures and recovery near the affected form. Retain entered case details when submission fails; use an inline alert in the dialog. https://design-system.service.gov.uk/components/error-message/

## Screen and interaction plan

1. Overview: onyx rail, white top bar, concise review heading, isolated orb, real case counts, searchable/filterable case list, useful no-match and empty states.
2. Case: original documents, source text and findings in matching DOM/visual order. At medium widths, documents/source share a row and findings follow. At mobile widths, stack them. No hidden evidence or horizontal page scrolling.
3. Sign-in: same palette and type system, meaningful field labels and existing session-auth behavior. No external requests added.
4. State polish: clear focus rings, disabled actions with explanatory copy, accessible dialogs, readable status labels, reduced-motion behavior and truthful preview labeling.
5. Validation: syntax and existing app checks, contrast calculations, synthetic UI interactions and desktop/mobile inspection where the environment allows a browser. Offline fixtures must be isolated from deployed static assets and make no external requests. Passing UI fixtures is not end-to-end production API validation.

## Release boundary

This work changes local UI source and an explicitly labeled standalone preview. The live Render app requires a separate image build and deployment. The neural extractor remains unqualified; neither the style nor the preview claims otherwise. No new paid action is part of this change.

## Implemented and checked

- Replaced the graphite theme with white/onyx/mint tokens and responsive layout; preserved Canvas2D and reduced-motion behavior.
- Added title/ID search with status filtering and announced result count. Kept real API-derived counts in production.
- Restored matching source/DOM order, added dialog names, form error recovery and case/source keyboard focus. Cleared stale source text when opening an empty case.
- Produced `artifacts/policypilot-ui-preview.html` and `artifacts/policypilot-login-preview.html`. The preview substitutes in-memory synthetic fixtures, blocks network with CSP, and does not ship fixtures in the production static directory.
- `node deploy/tests/check_ui.mjs` passed search, filter, conflict display, citation focus, polling preservation, empty case, create failure/success, back navigation and HTML escaping using DOM doubles.
- `python -B -m unittest deploy.tests.test_ui_design` passed 3 tests, including palette contrast calculations, dialog/form semantics and preview isolation. JavaScript syntax checks passed.
- `python -B -m unittest discover -s pilot/tests` ran 114 tests: 87 passed, 27 skipped because API dependencies are not installed here.
- Actual visual browser inspection is incomplete. Installed Chrome failed during launch with a sandbox socket permission error; Firefox headless exited before rendering. These are not browser pass results or WCAG certification. No screenshot was produced.
- No image published, Render deployment changed, model loaded or paid resource started.

## Browser handoff

Open the generated workspace preview in a browser. Check at 1440px, 768px, 390px and 320px, including browser zoom, keyboard-only navigation and reduced motion. Open SYN-C003, follow both conflicting admission-date citations, create a synthetic case, use search/status filters, and inspect dialogs. Open the separate login preview for input/focus/error states; do not enter real credentials there. The live authenticated upload/download flow still requires its own API integration checks before release.

## Canvas2D motion refinement

The overview orb animates decoratively even while the model is disconnected. Mint ribbons rotate around a shaded core with a slow breathing radius, three sparse orbit points and a small pointer offset. Busy states rotate faster. A labeled Pause/Resume motion button controls animation; operating-system reduced-motion preference makes the scene still and hides the unnecessary toggle. Animation suspends when hidden or out of viewport, caps pixel ratio at 1.5 and draws at approximately 25fps. Smaller status orbs animate only in busy states. No provider readiness is inferred from decorative motion.

Canvas API-double checks passed drawing, animation scheduling, pixel-ratio cap, pause/resume, hidden/offscreen suspension and reduced motion. Existing UI logic and 3 design checks also passed. Actual visual browser verification and live deployment remain outstanding due to the previously documented sandbox browser launch failure.
