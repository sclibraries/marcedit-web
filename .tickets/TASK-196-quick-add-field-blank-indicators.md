Title: Treat blank Add field indicators as MARC blanks

Scope:
- Make blank Indicator 1 and Indicator 2 inputs in Quick Add field produce
  the MARC blank character rather than an empty string.
- Preserve explicit indicator characters and all existing validation.

Success Criteria:
- A cataloger may leave either Add field indicator input blank and pass
  validation.
- The resulting field has a literal MARC blank indicator in that position.
- Explicit one-character indicators remain unchanged.
- Regression tests cover blank and explicit indicators.

Status: In-Progress
