# Development notes

## Scope

The goal is a useful local tool that is understandable enough to explain in an interview. First get the request runner right, then put an editor and history around it. The fault-injection demo makes failures reproducible without depending on third-party uptime.

Forms are ordinary Qt widgets. Validation lives in small dataclasses rather than a general form engine. Some UI checks repeat; that is acceptable here, but transport and credential validation are centralized. The UI uses neutral Windows-style controls, not a web view.

## Decisions worth reviewing

- Results intentionally omit response bodies. This limits debugging detail, but makes accidental secret leakage less likely. Local suites can still contain sensitive data and aren't encrypted.
- No automatic retries: a flaky response should be visible, and automatically repeating a POST could create duplicate changes. Users choose explicit rounds.
- Requests are sequential. Results and cancellation stay easy to reason about, and this isn't a stress-testing tool.
- TLS verification stays on. Redirects and environment proxy discovery stay off so requests don't silently move to another host.
- Runs are saved after the worker finishes, including explicit cancellation. A database failure does not discard the in-memory result: it can still be exported.
- JSON comparisons check types as well as equality; JSON `true` must not accidentally pass an expected numeric `1` check.
- Existing export files are never silently overwritten. Importing a suite never overwrites one with a matching ID.

## What is not claimed

No production users, enterprise deployment, uptime guarantees, load-test accuracy, signed installer, Windows Store publication, or commercial release. Automated GUI tests and screenshots aren't a substitute for usability testing on another person's PC.

Next cleanup: split check editing and history presentation out of `gui.py`, add retention controls, and expand packaging tests before publishing binaries. Do not add abstractions purely to make the code look bigger.
