# Validation and design notes

## Implemented and checked

- Whole-app profiles use distinct Electron user-data directories and Codex homes.
- Installed Linux app code explicitly resolves `CODEX_ELECTRON_USER_DATA_PATH`
  before the default `Codex` user-data directory and reads `CODEX_HOME`.
- An internal app launcher uses both environment variables plus `--user-data-dir`.
  This is implementation evidence, not a supported public compatibility contract.
- Twenty-three unit tests passed locally on Linux with Python and psutil 7.2.2.
- Tests cover isolated homes, default launch, invalid labels, dry-run behavior,
  operation order, unknown profiles, locking, update exit codes, Windows update
  targeting, private atomic config writes and close timeout without forced kill.
- Real credentials and user-data contents were never inspected or copied.
- The development chat's app was not closed. No live update installation ran.

## Manual acceptance checks still required

Perform from an independent terminal on each target OS:

1. Initialize and run `switch default --dry-run`; confirm the executable path.
2. Add two profiles. Sign into different accounts in each and verify their names
   in the whole-app profile menu, including Chat and Work.
3. Close/switch between them repeatedly; confirm cached login survives and the
   authentication callback reaches the correct profile.
4. Check whether OS-keyring credentials remain isolated by profile. If accounts
   bleed across profiles, this version is incompatible with that app/storage mode.
5. Confirm the original app profile remains accessible via `switch default`.
6. Run the normal update check with and without an available update, and offline.
7. Install an available update explicitly. Recheck executable discovery, launch
   permissions, cached authentication and profile isolation after updating.
8. Confirm closing handles tray/background windows and waits for real app exit.
9. Confirm cancellation, refusal to close and an invalid executable give useful
   output without deleting or overwriting account state.

Windows Store executable discovery, direct MSIX launch, PowerShell wrapper and
whole-app authentication have not been manually validated here. CI is unit-level
validation only and is not a substitute for these checks.

## Decisions

Use isolated live profile directories rather than taking snapshots of tokens or
replacing shared auth.json. Let the app own token refresh. Do not promise browser-
free enrollment or permanently valid sessions. Check updates by default and
install only with an explicit flag. Do not force-kill the desktop app. Keep all
local account state outside the source repository. Do not migrate the existing
profile automatically.

## Account menu changes

- Old configs with string profile names still work without migration.
- Account details are explicitly user-entered; no credentials are inspected.
- Active profile detection checks app launch arguments, excludes helper
  processes, and refuses to guess when multiple profiles are detected.
- Green indicates an open profile (or the profile open immediately before
  switching), not verified sign-in. Last-opened state is separately labeled.
- Tests cover metadata display, menu enrollment/cancellation, input sanitization,
  TTY/NO_COLOR handling, named selection, old configs and ambiguous open profiles.
- Live terminal rendering and real account switching still need manual checks.
