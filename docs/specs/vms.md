# Mode 3: VMs

Mode 3 runs the control plane in one VM and the code worker in another. Each VM has a kernel of
its own. An agent in the code VM changes only the code VM.

## The hypervisor

FA1 runs QEMU on every platform, with the platform's accelerator.

| platform | accelerator | QEMU comes from | admin step, once |
|---|---|---|---|
| Linux | KVM | the distribution: `apt install qemu-system-x86 qemu-utils` | access to `/dev/kvm`, if the person has none: `adduser <person> kvm` |
| macOS | HVF | the app's archive | none |
| Windows | WHPX | the app's archive | enable Windows Hypervisor Platform, then reboot |

- The guests are amd64, and arm64 on Apple Silicon.
- Each QEMU runs as the person, with `-sandbox on`.
- The Checks screen shows each admin step as one command, with what it changes.

## The VMs

| VM | memory | network cards | runs |
|---|---|---|---|
| control | 4 GB | user-mode, and the link | Robinauts' server, and the MCP servers in Docker |
| code | 4 GB | the link alone | the Claude Code worker in Docker |

### Network

- **The control VM's user-mode card** reaches the internet through QEMU. QEMU forwards
  `127.0.0.1:<port>` on the host to the front listener on this card.
- **The link** joins the two VMs and nothing else. It is a QEMU `stream` network over a Unix
  socket in the app's folder. The control VM is `10.77.0.1/30` on it, the code VM `10.77.0.2/30`.
- **The code VM's only card is the link.** Its default route is the control VM.

The control VM's firewall decides what the code VM reaches:

- the worker listener and the MCP servers, on the link;
- the internet, through the control VM, masqueraded;
- nothing in the private ranges, link-local addresses or the user-mode gateway, which is the
  host.

The server listens on each card for its own purpose:

```sh
robinauts start --local --host 10.0.2.15 --public-host 127.0.0.1 --port <port> \
    --worker-host 10.77.0.1 --worker-port <port + 1>
```

The code VM reaches the worker listener on the link. The front listener is on the user-mode card
alone.

### Disks

Each VM has four drives:

| drive | written by | holds |
|---|---|---|
| base | the build | the role's system, read-only after the build |
| overlay | the VM | the changes to the system since the last start from base |
| data | the VM | the records in the control VM; the workspaces and transcripts in the code VM |
| config | the app | the secrets and the settings, read-only, made by QEMU from a folder (`fat:ro:`) |

- An update builds a new base and a new overlay. The data drive stays.
- A reset of the code VM deletes its overlay and its data drive.
- The control VM reads the launch secret and the model keys from its config drive.
- The code VM reads its token, the Claude Code token and the GitHub token from its config drive.

## The build

FA1 builds each VM's base on the host. Every step runs in a VM. The host runs QEMU alone.

1. The app downloads Debian's `genericcloud` image for the guest architecture, its
   `SHA512SUMS` and `SHA512SUMS.sign`.
2. The app checks the signature with Debian's cloud image key, which FA1 ships. Then it checks
   the image's checksum.
3. The app boots a build VM: the Debian image, an overlay and a seed with the role's recipe. The
   build VM uses the user-mode network alone.
4. The recipe installs Debian's packages and Docker. It downloads Robinauts at the pinned
   commit and builds the role's images. Then the build VM shuts down.
5. `qemu-img` makes the overlay the role's base.

The recipes are cloud-init files and shell scripts in this repository, under `vms/`.

## Starting

1. The app writes each VM's config folder.
2. The app starts the control VM, and waits for `/auth/session` to answer on `127.0.0.1`.
3. With no worker token yet, the app creates one and writes it to the code VM's config folder.
4. The app starts the code VM.
5. The app asks for a ticket and opens Robinauts.

## Open

- The link on Windows, where QEMU's Unix sockets need checking. A loopback TCP port is the
  fallback.
- The config drive as a cloud-init seed, which needs the label `cidata`.
- The source of the QEMU build for the macOS and Windows archives.
- The build time and the download size: not measured.
