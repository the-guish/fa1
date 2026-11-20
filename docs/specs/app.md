# The app

The app is the one part of FA1 on the host. It is a Tauri program: a Rust core and a webview for
its screens.

## Actions

- The core runs a fixed list of actions. Each action runs one program with a fixed list of
  arguments, without a shell.
- Each action writes the program and its arguments to the app's log before it runs.
- `fa1 --plan` prints the actions of the first start, and runs none of them.

| action | mode 2 | mode 3 |
|---|---|---|
| check the prerequisites | `docker version`, `docker compose version` | the accelerator, `qemu-system-*`, `qemu-img` |
| download | nothing: the build fetches Robinauts at the pinned commit | Robinauts at the pinned commit, and Debian's cloud image with its signed checksums |
| build | `docker compose build` | a build VM per role ([vms.md](vms.md)) |
| start, stop | `docker compose up`, `docker compose stop` | `qemu-system-*` per VM, a signal to stop |
| logs | `docker compose logs` | each VM's console, written to a file |
| reset the code worker | remove its container and its volumes | delete its overlay and its data disk |
| remove everything | `docker compose down --volumes --rmi all`, then the folder | stop the VMs, then the folder |

The app also speaks HTTP to the control plane on `127.0.0.1` ([core.md](core.md)).

## The window

The app has one window, so the system's window switcher shows it once. The window holds three
webviews:

| webview | shows | calls the core |
|---|---|---|
| `bar` | the tabs, Admin and App, along the top | yes |
| `admin` | FA1's own screens, bundled with the app | yes |
| `app` | Robinauts, at `127.0.0.1`, signed in with a new ticket | no |

- The tabs share the space below the bar. The core shows one tab and hides the other.
- On Linux, Tauri packs the webviews in the window's GTK box, and the box sets their places. The
  app holds the bar at the top of the box, at its own height, through the `gtk` crate, which
  Tauri already uses.
- The first switch to App opens Robinauts. "Open Robinauts" on the Status screen loads it again,
  with a new ticket.
- A capability lists each command the bar and the admin screens may call. The capability names
  webviews, because a window's label also grants every webview in that window.
- The `app` webview is in no capability. The core refuses its calls.
- The webviews share one WebKit context. Robinauts and FA1's screens are different origins, so
  their cookies and storage stay apart.
- One window with several webviews needs Tauri's `unstable` feature. The feature's API may change
  between Tauri's minor versions, so an update of Tauri runs the journey.

WebKitGTK lets one WebKit context alone take WebDriver automation. A webview with its own data
folder is out of the journey's reach, so the `app` webview keeps the shared context.

## The folder

The app writes to one folder:

| platform | folder |
|---|---|
| Linux | `$XDG_DATA_HOME/fa1`, `~/.local/share/fa1` by default |
| macOS | `~/Library/Application Support/FA1` |
| Windows | `%LOCALAPPDATA%\FA1` |

It holds:

- `settings.toml`: the mode and the port.
- `secrets/`: the launch secret, the keys and the worker's token, readable by the person alone.
- `downloads/`: the sources and the images the build reads.
- `compose/` in mode 2, `vms/` in mode 3. `compose/apps/` holds FA1's applications and its
  host of them ([apps.md](apps.md)).
- `logs/`: the actions and the parts' output.

## Screens

1. **Welcome.** The three modes, each with what it protects against, and the setup folder's
   location ([setup-folder.md](setup-folder.md)).
2. **Checks.** The prerequisites of the chosen mode, the free memory and the free disk.
   A missing prerequisite shows the exact command that installs it.
3. **Keys.** The model providers' keys, the Claude Code token and the GitHub token. The rest of
   the person's settings is in the setup folder.
4. **Build.** The progress of each action, and its log.
5. **Status.** Each part and its health, its log, a button that opens Robinauts in the App tab,
   and the setup folder: its location, **Refresh**, and **Change**.
6. **Reset the code worker.**
7. **Update.** A new release of FA1 rebuilds the images.
8. **Remove everything.** The list of what it deletes, then a confirmation.

## Distribution

FA1 is one `.tar.gz` archive per platform. The person unpacks it anywhere they can write, such
as `~/bin`.

| platform | archive | the system provides |
|---|---|---|
| Linux | `fa1-linux-<arch>.tar.gz`: the `fa1` program | WebKitGTK 4.1, and Docker or QEMU |
| macOS | `fa1-macos-<arch>.tar.gz`: `FA1.app` | WebKit, and Docker or QEMU |

- The app installs nothing by itself. The Checks screen shows the command for each missing
  prerequisite, and the person runs it. On Debian, that command is `apt install`.
- The workflow `release` builds the archives on GitHub's runners. A tag `v*` attaches them to a
  release, with their SHA-256 sums.
- Windows comes later, with mode 3.

## Tests

- The unit tests cover the pure functions of the core, with rows of inputs and outputs.
- The journey in `tests/e2e/` drives the real app and a real Docker engine through WebDriver. It
  walks the screens from a fresh folder to its removal. It runs on Linux, by hand:
  `tests/e2e/run.sh`.

## Open

- Signing and notarizing `FA1.app`, which needs an Apple Developer ID. Until then, the person
  opens it with a right click.
- The journey in a CI job: it needs Docker and builds every image.

## Removal

1. "Remove everything" runs the mode's removal action and deletes the folder.
2. The person deletes the unpacked archive.

What remains is what the person installed for the mode, such as Docker or QEMU. The last screen
names each one, with the command that removes it.
