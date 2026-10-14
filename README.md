# codex-switcheroo

### A simple codex account switcher for your chatgpt app. All in the terminal.

A Python command with Bash and PowerShell launchers for choosing a **whole
ChatGPT desktop app account profile** on Fedora or Windows.

Run one command to close ChatGPT, check for updates, pick a profile in the
terminal, and launch that profile. Each profile keeps its own desktop data and
Codex home. The `default` profile opens your existing app account.

**Status: experimental.** Profile-directory overrides were confirmed in the
installed Linux app code. Unit tests cover the command logic; live account
switching and Windows desktop behavior have not been validated. This is an
unofficial tool, with no guarantee that future app versions preserve the
internal profile-directory settings.

An account must be signed in once **on each computer**. Cached sessions should
avoid repeated browser authentication while valid, but expiry, revocation, SSO,
and app changes can require sign-in again. The tool does not bypass login or
verify the account identity; check the profile menu in the app after switching.

## Setup

Install Python 3.10 or newer and the current ChatGPT desktop app. Clone this
repository and open a terminal in its directory.

### Fedora

```bash
git clone https://github.com/JacobKronbeck/codex-switcheroo.git
cd codex-switcheroo
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
bash ./switcheroo.sh init
bash ./switcheroo.sh add personal
bash ./switcheroo.sh add work
```

Daily command:

```bash
bash ./switcheroo.sh
```

### Windows PowerShell

```powershell
git clone https://github.com/JacobKronbeck/codex-switcheroo.git
cd codex-switcheroo
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\switcheroo.ps1 init
.\switcheroo.ps1 add personal
.\switcheroo.ps1 add work
```

Daily command:

```powershell
.\switcheroo.ps1
```

If your execution policy blocks PowerShell scripts, the equivalent single
command is `.\.venv\Scripts\python.exe .\switcheroo.py`. All subcommands can
be passed to that command. Do not weaken system execution policy to run this tool.

Windows initialization searches installed ChatGPT/Codex Appx packages. If it
finds multiple executables or cannot find one, provide the installed desktop
executable explicitly with `init --app "PATH_TO_CHATGPT_EXE"`. The tool must launch
the actual executable to pass profile-specific environment variables; it cannot
use a Start menu shortcut or `shell:AppsFolder` activation. Store versions that
reject direct launch may be incompatible. After an update, run `doctor` if the
configured executable path moved, then edit `config.json` at the printed local
state path.

## First sign-in and later switches

1. Finish any running app tasks; run `switch personal` using your launcher.
2. Sign into the intended account in the new app window. A browser can be needed.
3. Run `switch work` and sign into the other account once.
4. Run the daily command and select either saved profile by number.
5. Check the account displayed in the app's profile menu.

Labels are local names you choose; they are not automatically discovered ChatGPT
accounts. Adding a label creates an empty profile. It does not authenticate it.
If an authentication callback opens the original app instead of the managed
profile, stop using the managed profile and report the app version and OS (never
send tokens or profile files). This remains a manual compatibility check.

To return to your original app, run `switch default`, or quit all managed
windows and open ChatGPT normally. Normal launches do not automatically reopen
the last managed account. Settings, local chats, plugins and connections in new
profiles start fresh; project source files can still be opened from shared disk
locations. Native Windows and WSL Codex homes are separate; WSL integration is
not covered by this version.

## Commands

Append these arguments to either launcher:

| Arguments | Behavior |
| --- | --- |
| `init [--app PATH]` | Create machine-local configuration |
| `add NAME` | Register another profile |
| `list` | Show available labels |
| `doctor` | Show local state path and executable status |
| `switch` | Close, check updates, prompt, launch |
| `switch work` | Select a profile without prompting |
| `switch --install-updates` | Run the package manager's update operation |
| `switch --skip-updates` | Skip the update check |
| `switch work --dry-run` | Describe actions without closing or launching the app |

A normal update check only reports available updates. Fedora uses
`dnf check-upgrade --refresh chatgpt`; an optional installation uses
`sudo dnf upgrade --refresh chatgpt` and may prompt for administrator access.
Windows uses `winget list --id 9PLM9XGG6VKS --exact --source msstore
--upgrade-available`; optional installation uses `winget upgrade` for that Store
ID. Update errors are reported as unknown status and the account menu remains
usable. Installers may require their own interaction. Other distribution or
installer types need `--skip-updates` and their usual update mechanism.

ChatGPT gets up to 20 seconds to close. On Linux the tool sends SIGTERM to
processes with the exact configured app executable; on Windows it asks matching
process windows to close. It never force-kills them. If closing times out, quit
ChatGPT manually and retry. Cancelling the menu leaves the app closed. Run this
from an independent terminal, because closing ChatGPT ends app-hosted work.

## Local storage and privacy

Linux state defaults to `~/.local/share/codex-switcheroo` (or beneath
`XDG_DATA_HOME`). Windows state is `%LOCALAPPDATA%\codex-switcheroo`.
`config.json` contains the local executable path and labels. Managed profile
state lives under `profiles/NAME/desktop` and `profiles/NAME/codex`.

The launcher sets `CODEX_ELECTRON_USER_DATA_PATH`, `CODEX_HOME`, and
`--user-data-dir` only for the new process. It never reads, copies, edits or
exports existing passwords, auth tokens or cookies. The app may store credentials
in these directories or the OS credential store. Linux directories are restricted
to the current user; Windows uses the user's local application-data permissions.
Treat the entire state directory as private credential material. Keep it on the
local computer, outside this repository and cloud-sync folders. Use disk
protection appropriate to your computer. Do not share profile directories
between Fedora and Windows; encrypted app state can be bound to its OS/user.

Machine-local paths belong in local `config.json`, never tracked configuration.
No runtime credentials or real account state ship in this repository.

## Development

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

CI runs the same tests on Linux and Windows with Python 3.10 and 3.13. Tests use
fake executables, temporary state and mocked process/update operations. They do
not close a real app, make live authentication requests or install app updates.
See [validation notes](docs/VALIDATION.md) for the required manual desktop checks.

## Sources

- [OpenAI authentication and login caching](https://learn.chatgpt.com/docs/auth)
- [Official Fedora install/update guidance](https://learn.chatgpt.com/docs/linux/linux-app)
- [Official Windows app and Microsoft Store ID](https://learn.chatgpt.com/docs/windows/windows-app)

The directory overrides are an observation of installed app code, not a
publicly documented account-switching API. This project is not affiliated with
OpenAI.
