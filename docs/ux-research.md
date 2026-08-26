# Field-use UX research

Origin is a responsive web application, not a separate native phone app. That choice reflects mixed-device farm work rather than an assumption that every farmer works from a phone or every farm workflow belongs on a desktop.

## What the evidence says

- The USDA's 2025 Technology Use report says 85 percent of US farms had internet access. Smartphones were used for farm business on 82 percent of farms, while desktop or laptop computers were used on 68 percent. Cellular data was the most common access method at 74 percent. Both device classes matter.
- Current farm operations products mirror that split. John Deere Operations Center provides a desktop web workspace and a mobile application for in-field information, maps, and work status.
- Farmers discussing spray records describe lightweight phone entry through tools such as Google Forms, Sheets, FieldView, Agworld, and purpose-built mobile apps, followed by later review or reporting. The recurring preference is simple capture with little duplicate entry.
- Farmers criticizing agricultural software repeatedly mention complicated interfaces, poor interoperability, unreliable connectivity, expensive proprietary data, and the feeling that a spreadsheet is faster. Trust and control over farm data are product requirements, not secondary legal copy.
- Field HCI research identifies sunlight, gloves or dirty hands, intermittent networks, local language, and trust as practical constraints. Large controls, visible status, draft recovery, and clear consequences are therefore more important than a decorative mobile layout.

## Product response

| Context | Likely device | Origin design response |
|---|---|---|
| Cab, field edge, or equipment yard | Phone or tablet | Large touch targets, one-tap recording, short task cards, offline status, local draft recovery |
| Farm office | Laptop or desktop | Full values, provenance, consent scope, receipts, export, and revocation |
| Cooperative or partner operations desk | Desktop | Dense request queue, run timeline, trace IDs, and boundary-test controls |

The farmer sees one coherent product across devices. Mobile styling does not remove desktop capability; it prevents the field capture step from failing when a phone is the available computer. Partner operations remain explicitly desktop-first.

## Design principles

1. Show the next real job, not a generic chatbot prompt.
2. Make capture fast, but never treat capture as permission to share.
3. Display recipient, purpose, expiry, and exact outgoing values before first delivery.
4. Keep Gemini's interpretation visibly separate from deterministic authorization.
5. Preserve work through weak connectivity and state clearly when the agent is offline or waiting.
6. Use at least 44-by-44-pixel interactive targets and high-contrast status labels.
7. Provide receipts, revocation, export, and honest deletion language so control remains legible after delivery.

## Sources

- [USDA NASS, Farm Computer Usage and Ownership, August 2025](https://www.nass.usda.gov/Publications/Todays_Reports/reports/fmpc0825.pdf)
- [John Deere Operations Center features](https://www.deere.com/en-us/products-solutions/technology-solutions/precision-ag-technology/operations-center/features/)
- [John Deere Operations Center Mobile](https://play.google.com/store/apps/details?id=com.deere.myoperations)
- [Farmer discussion: simple spray-record workflows](https://www.reddit.com/r/farming/comments/1dcs0c7/bestsimplest_ways_to_keep_up_with_spray_records/)
- [Farmer discussion: barriers to agricultural technology](https://www.reddit.com/r/farming/comments/12pg9ro/why_arent_farmers_embracing_ag_tech/)
- [Agriculture discussion: pain points in current farm software](https://www.reddit.com/r/Agriculture/comments/1f7903x/what_do_you_hate_most_about_current_agricultural/)
- [Ag Data Transparent core principles](https://www.agdatatransparent.com/principles)
- [Farm Data Principles](https://farmdataprinciples.com/)
- [Field-ready agricultural interface study](https://doi.org/10.3390/app16146985)
- [W3C target size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced)
