# Validation

## Automated coverage

Tests use only temporary fake profiles, fake stdio helpers and mocked app/update
processes. Coverage includes empty menus, preset hiding, original-account
discovery, visible numbering, multiple open accounts, green and plain-text
indicators, retained signed-out/stale identities, browser enrollment, cancellation,
timeouts, early/unrelated notifications, helper cleanup, duplicate reuse,
immediate launch, configuration compatibility, profile isolation, update-install
refusal and preservation of running windows.

The latest run passes all 83 tests. Additional coverage checks Ctrl+C quits
without another refresh (including enrollment cleanup), saved label editing and
removal across refresh/restart, and Docker page refresh/back/quit navigation,
inactive-service exit codes, missing commands and unsupported platforms.
Docker subprocess execution is mocked and checks the rootless user service without sudo.

These tests establish command and protocol behavior, not live desktop compatibility.

## Outstanding manual desktop checks

Run on both Fedora and Windows using an independent terminal:

1. Initialize on an installation without accounts. Confirm “No accounts”, Add
   account, Refresh, Back and Quit. Confirm no placeholder personal/work/default rows.
2. With an existing original-app login, confirm automatic email discovery. Check
   managed profiles from an older config also appear only after confirmed login.
3. Add a distinct account through the browser. Confirm its email appears only
   after successful completion and its desktop window opens automatically.
4. Check the account in both Chat and Work. Confirm the desktop recognizes the
   profile-scoped Codex login. If it asks for a separate login, record the app
   version and OS; this is a compatibility failure of the intended enrollment flow.
5. Open two different accounts simultaneously. Confirm signing into one does not
   change the other's identity, settings, sessions or access to ongoing work.
6. On Windows/X11 with window detection available, confirm both open signed-in
   account windows show green dots and green emails. Close one, keeping its
   background process running, and refresh; only the remaining window should be
   green. On Fedora Wayland with ChatGPT using XWayland, verify the same behavior
   using `xprop` without installing `wmctrl`. Native Wayland windows remain unknown.
   Repeat with NO_COLOR; the active marker should be readable without ANSI codes.
7. Select an already-open account. Verify correct activation where supported and
   no duplicate app instance. On Wayland or when activation fails, confirm the
   reopen request restores the selected profile's window. Repeat after closing
   its last window while leaving the app in the background; other accounts must
   remain open and the selected profile must retain its login.
8. Quit the picker, abort browser login with b, and let an enrollment time out. Confirm
   all original windows remain running and no new visible account is saved.
9. Add the same email with a different workspace selected in browser consent.
   Give it a workspace label. Confirm a separate numbered row and isolated window,
   and select both rows to verify each opens the intended workspace. Add the same
   email and workspace again: when the helper reports workspace IDs, confirm reuse
   of the original profile. Without IDs, confirm separate rows instead of email-only
   merging. Test case differences, expired sessions, and label retention after refresh.
10. Sign out from one saved account. Confirm its row remains with Sign-in required
    and no green indicator. Open and sign in again; confirm status recovers.
11. Temporarily make the Codex reader unavailable. Confirm cached account emails
    remain visible with Status unavailable and no green, then recover the reader.
12. Restart the app and computer. Confirm cached login persistence and isolation.
13. Check ordinary updates, including offline/error conditions. Confirm output is
    outside the picker and windows stay open. Attempt --install-updates with an
    open app: it must refuse. Quit all app instances before testing installation.
14. Recheck discovery, login persistence, activation and isolation after updating.
15. Select several accounts without restarting the script. Confirm one terminal
    screen is redrawn after every action, r updates closed/open windows, and q
    exits without closing windows. Test b during browser sign-in and q during
    browser sign-in. Confirm background capture and separate list commands can
    operate while the picker waits for input.
16. Test Windows Store executable discovery/direct launch and both shell wrappers.
17. Press Ctrl+C at the picker, during browser login, and while editing a label.
    Confirm the script exits without refreshing and existing windows stay open.
18. Use e to select an account and edit its label. Refresh and restart the picker;
    confirm the new label persists. Repeat with blank input to remove the label.
19. On Fedora, use d to view Docker Status. Confirm the rootless user service is
    queried without sudo or a password prompt. Check active
    and inactive service output, r to refresh, b to return, and q/Ctrl+C to quit.

Never include tokens, profile contents or raw authentication responses in reports.
Live browser authentication, account isolation, activation, Windows Store launch
and login persistence remain unvalidated until these checks are performed.

## Evidence and limitations

The earlier implementation inspected installed Linux app code and found desktop
user-data and CODEX_HOME overrides. These remain internal implementation details.
Browser login uses account/login/start, the helper-owned local callback,
account/login/completed and account/read from the
[official protocol](https://learn.chatgpt.com/docs/app-server).
Green reflects a detected open window plus fresh local signed-in metadata; it
does not verify remote entitlements or all other app surfaces. Native Wayland
window status remains unavailable; XWayland windows can be detected on Wayland.
Detection never falls back to a process-based green marker.
