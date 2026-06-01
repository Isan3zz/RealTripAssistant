# RealTrip Fresh Map Workbench UI Design

Date: 2026-05-20

## Goal

Redesign the RealTrip Assistant frontend so it feels like a fresh travel planning product, not a generic chat dashboard. The confirmed direction is a map-first planning workbench:

- A compact planning control area at the top.
- A large route/map stage below as the main visual focus.
- A full itinerary drawer that opens when needed instead of permanently occupying a large side panel.

The real map integration can arrive later. The UI should reserve the map surface now with a route-canvas placeholder so the future map SDK can replace that section without changing the rest of the page structure.

## Visual Direction

Use a clean, bright travel palette:

- Mint green for planning and route actions.
- Sea-salt blue for map surfaces and quiet panels.
- Sunlight yellow for highlights, budget chips, and warm travel accents.
- Deep teal for readable headings and primary actions.
- White translucent panels with soft shadows for a breezy, vacation-like feel.

Avoid the previous dark green and gold luxury direction. It felt too heavy for a travel planning assistant.

## Home Page Layout

Desktop layout:

1. Top navigation bar
   - Brand mark and RealTrip name.
   - Search-style field for city, attraction, hotel, or restaurant.
   - Health status and new trip action.

2. Top planning control area
   - Left: travel intent and preference chips such as days, budget, pace, transportation priority.
   - Center: AI planning chat with short message history and composer.
   - Right: itinerary summary with generated status, total days, estimated cost, pace, and travel priority.

3. Large bottom map stage
   - Full-width visual route canvas placeholder.
   - Route pins, day filters, transportation layer chips, and route summary cards.
   - Later replacement point for a real map component.

4. Itinerary drawer
   - Hidden or collapsed by default.
   - Opens from the bottom or side when the user clicks "View full itinerary", a day card, or a route pin.
   - Contains the full Day 1 / Day 2 timeline, costs, attention notes, and revision actions.

Mobile layout:

1. Header stays compact.
2. Map summary appears first.
3. Chat and itinerary become tabs or a segmented control.
4. Full itinerary opens as a bottom sheet.

## Component Boundaries

Implement the UI with clear sections so future map work is easy:

- `TopBar`: brand, search, health, new session.
- `PlanningControl`: preference summary, chat, and result summary.
- `MapStage`: route placeholder now, real map later.
- `ItineraryDrawer`: full structured itinerary details.
- `SessionList`: recent sessions, secondary on desktop and collapsible on mobile.

`MapStage` should accept itinerary-derived route points or placeholder points. It should not own chat state or session state.

## Interaction Rules

- Keep the chat available, but do not let it dominate the page.
- Make map and route output the visual center of the product.
- Keep full itinerary details one click away.
- When no final plan exists, the map stage shows a calm empty route state.
- When a plan exists, route pins and day filters become visible.
- If the backend or map data is unavailable, the placeholder canvas remains usable.

## Implementation Scope

First implementation should focus on the existing Vue frontend:

- Update `frontend/src/App.vue` design tokens.
- Restructure `frontend/src/views/TripList.vue` into the confirmed layout.
- Keep existing API calls, session restore, chat send, and structured plan parsing.
- Add local UI state for opening and closing the itinerary drawer.
- Keep `frontend/src/views/TripDetail.vue` visually aligned, but the main redesign priority is the home planning page.

No real map SDK is required in this phase.

## Verification

After implementation:

- Run `npm run build` in `frontend`.
- Check desktop layout at 1280px or wider.
- Check mobile layout around 390px.
- Confirm no horizontal overflow.
- Confirm full itinerary details remain accessible through the drawer.
- Confirm chat send, session restore, and generated plan rendering still work.
