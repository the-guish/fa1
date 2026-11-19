# fa1
let it lend you some arms

FA1 is a desktop app that runs [Robinauts](https://github.com/the-guish/robinauts) for one
person, with the coding agents kept apart from the rest: on the same host, in containers, or in
VMs. Start with [docs/specs/core.md](docs/specs/core.md).

Today FA1 offers the containers mode, on Linux and macOS.

## Install

1. Install Docker with Compose and Buildx. The app's Checks screen shows the commands.
2. Download the archive for your platform from the releases, and unpack it where you keep
   programs, such as `~/bin`:

   ```sh
   tar -xzf fa1-linux-x86_64.tar.gz -C ~/bin
   ~/bin/fa1/fa1
   ```

   On macOS the archive holds `FA1.app`. It is not signed yet: open it with a right click, then
   Open.

3. To see what the first start runs, without running it: `fa1 --plan`.

## Remove

The app's Status screen has "Remove everything". It deletes FA1's containers, volumes, images and
folder. Then delete the unpacked archive.

## Develop

- `cargo run --manifest-path app/Cargo.toml` runs the app. On Linux it needs WebKitGTK 4.1 and
  GTK 3 with their headers: `libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libsoup-3.0-dev`.
- `cargo test --manifest-path app/Cargo.toml` runs the unit tests.
- `tests/apps/run.sh <a checkout of Robinauts>` runs the review app's tests, on real git.
- `tests/e2e/run.sh` runs the person's journey on the real app and Docker, on Linux.
