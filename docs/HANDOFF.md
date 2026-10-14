# Account-picker implementation handoff

The working source is in this checkout. The checkout was initially empty; source
was copied from the earlier standalone deliverable as the baseline. No Git commit,
push or publication was performed.

## Decisions

- Keep the terminal picker and display confirmed account emails rather than
  internal profile names or plan/organization data.
- Discover the original account and preserve existing profile paths/configs.
- Add account invokes browser login in a new isolated home, then registers the
  confirmed identity and immediately opens a desktop window.
- Use profile-scoped file credential storage only for newly enrolled profiles;
  existing profiles retain their settings. Switcheroo never parses credentials.
- Keep all account windows running. Detect all open profiles, and activate existing
  windows using OS APIs when available; never launch duplicates for known-open
  profiles. Linux Wayland environments may require manual window selection.
- Duplicate enrollment reuses the original saved profile by case-insensitive email.
  Expired original sessions may still need sign-in in their desktop window.
- Preserve confirmed identities through logout and reader failures, with explicit
  status and no green indicator. Keep profile names for direct legacy commands.
- Watchers operate independently of last_opened so one account's launch does not
  cancel another account's identity capture.
- Explicit update installation refuses while app processes are running.

## Verification and remaining work

All 56 automated tests pass locally on Linux. Bash syntax checks and four
isolated CLI checks (initialization, empty picker/cancel, list and dry-run) pass. Test fixtures use
fake accounts/processes only. See VALIDATION.md for required real desktop checks;
Fedora/Windows authentication reuse, simultaneous desktop account isolation,
window activation and Windows Store launch remain outstanding. Windows CI has
not been run for this local change. Do not infer desktop compatibility from tests.


## Persistent picker and running-indicator correction

The picker now remains open after selections and enrollment. It redraws the screen,
keeps a single action message, and provides r Refresh, b Back and q Quit. Back at
home redraws the home picker; Back during browser login cancels only that enrollment.
Quit during login cancels enrollment and exits. Terminal EOF still ends the script.
State locks are scoped to refresh/enrollment/open actions, not waiting for input.

The installed Fedora configuration points to codex-launcher, which execs the
sibling ChatGPT binary. Process detection now includes that exact sibling path;
it does not match unrelated ChatGPT binaries or CLI helper processes. Earlier
path-only matching caused both live desktop profiles to be missed even with valid
signed-in metadata. No app windows were stopped or live login requests made.

Verified the corrected detector against the live default and work desktop
processes: both are recognized. Signed-in metadata was checked without printing
emails or credentials. Full enrollment and desktop isolation checks remain pending.
