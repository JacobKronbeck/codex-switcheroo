# codex-switcheroo

### A simple codex account switcher for your chatgpt app. All in the terminal.

Choose a saved ChatGPT account by email, or add one through browser sign-in.
Different workspaces under the same email can be saved as separate numbered choices.
Each managed account has its own desktop data and Codex home. Other account
windows stay open when you select an account or quit the picker. The picker stays
running after actions and redraws the terminal instead of appending a scrolling log.

**Experimental:** browser login uses the documented Codex app-server protocol,
but desktop profile isolation uses internal app settings. Live authentication,
simultaneous account windows, and Windows Store launches still require manual
validation. See [validation notes](docs/VALIDATION.md).

## Setup

### v0.1 release downloads

Download the Linux `.tar.gz` or Windows `.zip` package from
[GitHub Releases](https://github.com/JacobKronbeck/codex-switcheroo/releases/latest).
Extract it to a permanent folder before setup. These are Python source packages;
Python 3.10 or newer and the ChatGPT desktop app must already be installed.
Setup installs dependencies from PyPI and asks whether to create a desktop icon;
press Enter to skip it. No administrator access is needed for the shortcut.

**Linux (including Fedora):**

```bash
bash setup-linux.sh
# Explicit choice for unattended setup:
bash setup-linux.sh --desktop-icon
# Or: bash setup-linux.sh --no-desktop-icon
```

**Windows:** open PowerShell in the extracted folder:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup-windows.ps1
# Explicit choice for unattended setup:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup-windows.ps1 -DesktopIcon
# Or use -NoDesktopIcon
```

The execution policy option applies only to that PowerShell process. Keep the
extracted folder in place after creating a shortcut; rerun the shortcut installer
after moving it. On Linux, desktop environments may require **Allow Launching**.
Release archives do not have Git history: download a newer release to update.
The Linux desktop launcher's automatic Git updates apply to cloned checkouts.
`SHA256SUMS` provides SHA-256 hashes for both downloads.

### Manual setup from a checkout

Install Python 3.10 or newer and the ChatGPT desktop app. Open a terminal in this
repository. The reader uses the bundled Codex executable when found, otherwise
`codex` on PATH. Use `init --app PATH --codex PATH` if discovery fails.

### Fedora

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
bash ./switcheroo.sh init
bash ./switcheroo.sh
```

### Linux desktop icon

After the Fedora setup, install the launcher:

```bash
python3 install-desktop.py
```

Open **Codex Switcheroo** in the application menu, or double-click its Desktop
icon. If your desktop requests it, choose **Allow Launching**. GNOME installations
without desktop icon support can use the application menu and pin it to the dash.
The launcher opens a terminal and fetches from the configured Git upstream before
pulling with `--ff-only`. Local edits, untracked files, and ahead or diverged
history prevent pulling; unavailable GitHub access leaves the local copy usable.
Changed requirements are installed into the existing virtual environment after
a successful update. Keep this checkout at its current location, or rerun the
installer after moving it. Repository updates are separate from the ChatGPT app
update check inside the picker.

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\switcheroo.ps1 init
.\switcheroo.ps1
```

If PowerShell scripts are blocked, run `.\.venv\Scripts\python.exe .\switcheroo.py`
directly; all subcommands work with this command too.

Windows initialization searches installed ChatGPT/Codex Appx packages. Multiple
matches require `init --app PATH`. The executable must accept direct launch with
profile-specific environment variables; some Store versions may be incompatible.
Run `doctor` if an app update changes its path, then edit the local config at the
printed state path.

For an optional Windows desktop shortcut after manual setup:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-desktop.ps1
```

## Account picker

An installation with no confirmed accounts displays:

```text
ChatGPT accounts
  No accounts
  Add an account to get started.
  a. Add account
  e. Edit account label
  d. Docker Status
  r. Refresh
  b. Back
  q. Quit
Choose account number, a, e, d, r, b, or q:
```

A signed-in account in the original app profile is discovered automatically.
Existing signed-in managed profiles are also discovered. Unsigned-in preset
profiles are hidden, and their directories remain intact. Accounts are numbered
by their visible list order:

```text
ChatGPT accounts
  1. ● first@example.test [open]
  2. second@example.test
  a. Add account
  e. Edit account label
  d. Docker Status
  r. Refresh
  b. Back
  q. Quit
```

On color-capable interactive terminals, both the dot and email are green and the
`[open]` text is omitted. `NO_COLOR`, redirected output, and unsupported terminals
use the plain-text marker. Green requires a detected open desktop window belonging
to the profile and a freshly readable signed-in local session. Closing the window
removes its green indicator after Refresh, even if the app runs in the background.
Windows uses visible window handles; Linux uses `wmctrl` or `xprop` for X11 and
XWayland windows, including ChatGPT on Fedora Wayland. For native Wayland windows
or when window detection is unavailable, no green indicator is shown and the picker reports
“Window status unavailable on this desktop.” It does not prove remote entitlement
or independently verify the Chat and Work surfaces.

Select an account number to open its window without closing other accounts.
Selecting an already-open account attempts OS window activation. Windows uses
native window handles; Linux uses `wmctrl` when available and able to see the
window. If activation fails (including on Wayland), the tool launches the same
profile command again to ask the desktop app to restore or recreate its window.
The desktop's single-instance handler reuses that profile's running instance.
After launching, the picker checks for the selected account's visible window
every quarter second for up to 10 seconds, then refreshes the list automatically.
Once detected, a signed-in account shows its green running indicator without
pressing Refresh. If the window cannot be confirmed or detection is unavailable,
the picker reports that instead of claiming the window is running.
Account and process status refresh before each picker display and before opening.
After a selection, the picker stays running. Press **r** to refresh, **b** to
return to the home screen, or **q** or **Ctrl+C** to quit. Account windows keep running.
Ctrl+C also quits during enrollment, editing, refresh, or Docker status. Screen
clearing applies to interactive terminals; redirected output remains plain text.

Type **q#** (for example, `q2`) to request that just that account's window quit.
Type **q*** to quit all account windows, including accounts removed from the list.
Type **remove #** (for example, `remove 2`) to remove an account from the saved
list. Local profile data and existing windows are kept; the removed account stays
off the list after refresh and restart. Use **a** to add an account again.
Press **h** for a concise command reference, then **b** to return.

Press **e** to select an account and edit the label after its email. Enter a blank
label to remove it. Labels are saved locally and retained across refreshes and
restarts for the same account/workspace.

Press **d** for **Docker Status** on Linux. This runs `systemctl --user --no-pager
status docker` for rootless Docker under your user account, without sudo. A container
table lists names, IDs, images, status/uptime, health (when configured), and ports
for running and stopped containers using the current Docker CLI context. Missing
Docker, connection errors, and empty container lists are reported on the page.
The page also displays service output, including inactive or failed status; **r** refreshes both,
**b** returns to accounts, and **q** or **Ctrl+C** quits.

Previously confirmed accounts stay visible after logout or a metadata-reader
failure, marked **Sign-in required** or **Status unavailable**, without green.
Select an expired account to open its app window and sign in again if requested.
Emails serve as usernames. Optional workspace labels distinguish choices such as
`user@example.test — Alliant Engineering` and `user@example.test — Personal account`.
Same-email entries without labels (or with identical labels) include a Workspace
number to distinguish them. Plan details and internal profile names stay hidden.
If email is unavailable, a generic ChatGPT account label is shown.

## Add account

Select **a. Add account**, or run `add` using either launcher. No account name or
email entry is required. An isolated internal profile is generated, and the
Codex helper starts browser authentication and owns the local callback. Choose
the intended account and workspace in the browser. After sign-in, the interactive
terminal offers an optional workspace label, such as **Alliant Engineering** or
**Personal account**. This label describes your choice; it does not select the
workspace in the browser. If automatic browser opening fails, the
terminal prints the login URL. During sign-in, enter **b** to return to the
picker or **q** to quit (press Enter after the key).

The tool waits up to five minutes. Ctrl+C cancels enrollment and quits the
picker. Failed, cancelled or timed-out enrollment creates no visible account and
removes only its newly created, unregistered directory. Successful login is
confirmed through `account/read`, saved, and immediately opens that account's
window. To save another workspace for the same email, choose **a. Add account**
again and select that workspace during browser consent. Each workspace gets its
own isolated profile and numbered choice.

When Codex reports a workspace ID, the same email and workspace ID reuse the
existing saved profile. Different workspace IDs remain separate. Older helpers or
sessions that do not expose the ID keep new logins as separate entries, since an
email alone cannot identify the workspace. Workspace IDs are read through the
app-server's experimental metadata capability; credentials are never decoded.
If an existing reused profile's session has expired, its window may request sign-in again.
For a label from the command line, use `add --workspace "Personal account"`.

Accounts must be signed in once on each computer. Valid cached sessions should
avoid repeated authentication; expiration, revocation, or organization policies
can require sign-in again. New desktop profiles start with fresh settings and
local app data. Normal app launches still use the original profile. Native
Windows and WSL homes remain separate; WSL integration is outside this version.

## Commands

Append arguments to `bash ./switcheroo.sh` or `.\switcheroo.ps1`:

| Arguments | Behavior |
| --- | --- |
| `init [--app PATH] [--codex PATH]` | Create local configuration |
| `add [NAME] [--workspace LABEL]` | Browser sign-in, save confirmed workspace, open window, continue in picker; NAME is an optional legacy internal identifier |
| `list` | Refresh and show confirmed accounts and open indicators |
| `doctor` | Show state path and executable status |
| `switch` (also the default) | Check updates, show picker, open or activate selection |
| `switch PROFILE` | Open a legacy internal profile directly, including `default`, then continue in picker |
| `switch --skip-updates` | Skip the package update check |
| `switch --install-updates` | Install updates only when no app processes are running, then show picker |
| `switch PROFILE --dry-run` | Describe selection and opening without account reads, updates or app launches |

Update checks run outside the picker. Fedora uses `dnf check-upgrade --refresh
chatgpt`; installation uses `sudo dnf upgrade --refresh chatgpt`. Windows uses
`winget list --id 9PLM9XGG6VKS --exact --source msstore --upgrade-available`;
installation uses `winget upgrade` for that ID. Unsupported or failed ordinary
checks leave selection usable. Explicit installation refuses while any matching
app process is running; quit windows and background instances yourself first.
Explicit **q#** and **q*** commands request account windows quit. Fedora codex-launcher
wrappers are matched to their sibling ChatGPT process for running indicators
and update-install protection.

## Local storage and privacy

Linux state lives under `~/.local/share/codex-switcheroo`, or `XDG_DATA_HOME`.
Windows uses `%LOCALAPPDATA%\codex-switcheroo`. Local `config.json` stores the
executable path, internal profile identifiers, allowlisted account metadata and
confirmation status, workspace IDs when available, and optional workspace labels.
Existing configs and profile paths remain compatible.
Legacy `last_opened` is retained for compatibility but never displayed as status.

Managed data lives under `profiles/NAME/desktop` and `profiles/NAME/codex`.
The launcher sets `CODEX_ELECTRON_USER_DATA_PATH`, `CODEX_HOME` and
`--user-data-dir` for launched processes. Newly enrolled Codex homes specify
`cli_auth_credentials_store = "file"` so their login credentials stay scoped to
the profile rather than a shared keyring. Existing profiles and their storage
settings are preserved. Codex owns credential creation and refresh; switcheroo
does not parse, copy or export tokens or browser cookies. Raw protocol responses
are never logged or saved. No API key is required.

Treat the entire runtime state directory as private credential material. Keep
it outside this repository and cloud-sync folders, and do not share profile
state across operating systems. Linux directories and configuration files have
private permissions; Windows uses local application-data permissions.

## Development

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

CI runs on Linux and Windows with Python 3.10 and 3.13. Tests use fake accounts,
temporary state and mocked processes, including fake stdio protocol servers.
They do not make live authentication requests, stop a real app or install updates.

[Project handoff](docs/HANDOFF.md) records implementation decisions and remaining
manual checks. See [v0.1 release notes](docs/releases/v0.1.md) for platform packages
and installation options.

## Sources

- [Official app-server browser login and account protocol](https://learn.chatgpt.com/docs/app-server)
- [OpenAI authentication](https://learn.chatgpt.com/docs/auth)
- [Fedora app guidance](https://learn.chatgpt.com/docs/linux/linux-app)
- [Windows app guidance](https://learn.chatgpt.com/docs/windows/windows-app)

Desktop-directory overrides are an observation of installed app code, not a
supported account-switching API. This project is not affiliated with OpenAI.
