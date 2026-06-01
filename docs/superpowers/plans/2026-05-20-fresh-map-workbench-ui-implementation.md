# Fresh Map Workbench UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the confirmed RealTrip home page redesign: top planning controls, large bottom map stage, and full itinerary drawer.

**Architecture:** Keep the existing Vue single-file component flow and existing API/session logic. Restructure `TripList.vue` template around semantic UI sections, add local drawer state, and refresh global tokens in `App.vue`. Do not add a real map SDK in this phase.

**Tech Stack:** Vue 3, Vite, TypeScript, Element Plus, scoped CSS.

---

## File Structure

- Modify `frontend/src/App.vue`: fresh travel color tokens and global Element Plus styling.
- Modify `frontend/src/views/TripList.vue`: new top control layout, bottom map placeholder stage, itinerary drawer, responsive behavior.
- Verify with `npm run build` in `frontend`.
- Verify visually in the browser at desktop and mobile widths.

## Task 1: Fresh Global Tokens

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Replace global color direction**

Set CSS tokens to mint, sea-salt blue, sunlight yellow, deep teal, and clean white surfaces. Keep existing Element Plus selectors so component behavior does not change.

- [ ] **Step 2: Build verification**

Run: `npm run build`

Expected: exit code 0.

## Task 2: Home Page Structure

**Files:**
- Modify: `frontend/src/views/TripList.vue`

- [ ] **Step 1: Preserve existing script state**

Keep chat state, session restore, `parsedPlan`, `hasFinalPlan`, `handleSend`, and parsing helpers.

- [ ] **Step 2: Add drawer state**

Add:

```ts
const itineraryDrawerOpen = ref(false)
```

Open the drawer when a generated plan arrives and when the user clicks "查看完整行程".

- [ ] **Step 3: Replace template layout**

Use:

- `.workbench-topbar`
- `.planning-control`
- `.intent-panel`
- `.chat-panel`
- `.summary-panel`
- `.map-stage`
- `.itinerary-drawer`

Keep existing message rendering and composer wiring.

- [ ] **Step 4: Build verification**

Run: `npm run build`

Expected: exit code 0.

## Task 3: Map Stage and Itinerary Drawer Styling

**Files:**
- Modify: `frontend/src/views/TripList.vue`

- [ ] **Step 1: Implement route canvas placeholder**

Use CSS-only map lines, route pins, day chips, and route summary cards. The placeholder must work both with and without final plan data.

- [ ] **Step 2: Implement drawer styles**

Make the drawer a bottom sheet on desktop and mobile, with overlay, close action, summary strip, and all existing day/category/segment content.

- [ ] **Step 3: Responsive verification**

Check desktop around 1280px and mobile around 390px. Confirm no horizontal overflow and that the drawer remains accessible.

## Task 4: Final Verification

**Files:**
- Verify only.

- [ ] **Step 1: Production build**

Run: `npm run build`

Expected: exit code 0. Vite chunk-size warnings are acceptable if no compile errors occur.

- [ ] **Step 2: Browser smoke test**

Open `http://127.0.0.1:3000/`.

Confirm:

- The page uses the fresh map workbench layout.
- Chat input and send button are visible.
- The bottom map stage is large.
- The full itinerary is accessible through the drawer button.
- Mobile width has no horizontal overflow.
