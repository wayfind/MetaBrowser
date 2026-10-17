# Build topology

## Development Mac

Available disk measured on 2026-10-14: about 19 GiB. This machine can build the
Zig contract/consumer but should not host the full Chromium checkout/build.
Chromium build tooling may use Python; the shipped MetaBrowser control runtime
does not. Avoid confusing a build dependency with an application wrapper.

## H200 Linux builder

TinyKG nodes 10355, 11648, 12106 describe `gpu221`, Ubuntu 22.04, H200 hardware
and `/data`. The last cited resource check reported 192 CPUs, about 2 TiB RAM
and about 28 TB on `/data`; these are historical, not current measurements.
Chromium compilation uses CPU, RAM and disk. GPU model services need not be
stopped and are not part of the compiler workload. Check current load and
choose a bounded job count before building; do not start by occupying all CPUs.

The target SSH endpoint is `ubuntu@114.94.190.2:2216`. The non-production
jump host remembered in node 11648 is `ubuntu@119.45.6.42:22`.
That node explicitly says not to switch builds/experiments back to the old
production jump host. Do not replace this instruction with older memory hits.

Initial 2026-10-14 connection evidence from this Mac:

- Jump host reachable; current default public-key authentication rejected.
- Direct H200 TCP connection reset during key exchange, before authentication.
- No remote source download, tool installation, service restart or compilation
  has run. Failure to reach the remembered path does not prove H200 rejects
  this Mac's key; an alternative established route may exist.

After the user added authorization, the Mac's `id_ed25519` successfully
authenticated to H200 through `shuzuan@58.211.6.133:104` TCP forwarding. This
uses the Mac key at H200, not a copied jump-host private key. The old production
jump host is not used. `scripts/h200.sh` preserves this verified route.

Current read-only measurements: Ubuntu 22.04.5 x86_64, 192 CPUs, 1.9 TiB
available memory, `/data` 2.4 TB free, load about 9, passwordless sudo available.
Dedicated directory `/data/metabrowser` is owned by ubuntu. Initial build
parallelism is capped at 32. No GPU or model service operation is authorized
or needed by this build.

The existing internal HTTP proxy can reach GitHub and Google Storage, while
the first official googlesource Git/TLS requests failed. Network preparation
must finish before a source checkout is claimed complete. The Linux Zig
toolchain is pinned to official 0.16.0 archive SHA-256
`70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00`.
`prepare-builder.sh` stages that toolchain and runs the local contract tests;
it does not claim to compile a Chromium engine SDK.

The official Chromium 154.0.8037.97 source archive (4,174,250,340 bytes) is
cached on H200 and verified against official object metadata and the SHA-256
now pinned in `upstream.lock.json`. Extraction uses a dedicated directory;
extraction completed with `SOURCE_EXTRACTED`, and `chrome/VERSION` matches
154.0.8037.97. The official pinned depot_tools archive
is transferred from the Mac, where its upstream endpoint is reachable, then
hash-checked on H200. Zig 0.16.0 was obtained through a mirror from Zig's
official community-mirror list and checked against Zig's official SHA-256.

Both cross-compiled standalone tests and builder-native Zig Debug/ReleaseSafe
contract builds passed on H200. This is contract/compiler readiness, not a
completed browser engine or native agent SDK. Chromium integration and
MetaCodes embedding remain open work.

Before mutation: confirm OS/architecture, current load, free disk, ownership
of the selected work directory, outbound access, tool versions, and existing
Chromium checkouts. Stage a dedicated build root such as `/data/metabrowser`
only after confirming it is writable and unused. Start with read-only checks.

## Build inputs and gate

`upstream.lock.json` records the candidate Chromium and MetaCodes commits.
Prepare depot_tools, fetch the pinned Chromium source/dependencies, install
Linux build prerequisites, apply the reviewed MetaBrowser integration, build
native browser/bridge, run unit and browser integration tests, and package the
complete Linux SDK with resource hashes and notices.

`out/linux-x86_64/` must record GN args, toolchain identity, commit/patch hashes,
test receipts and artifact hashes. A successful compiler exit without a
native browser task/approval/cancellation test does not establish acceptance.

Upstream instructions:
[Linux build requirements](https://github.com/chromium/chromium/blob/main/docs/linux/build_instructions.md),
[macOS build instructions](https://github.com/chromium/chromium/blob/main/docs/mac_build_instructions.md).

The upstream Linux guide calls for at least 100 GB free disk. H200's remembered
resources meet that guidance if still available; the current Mac does not.

## macOS ARM64 cross-build (current target)

The product target is macOS ARM64, compiled on Linux H200 and returned to this
Mac. Xcode 26.2's actual SDK was transferred to the dedicated builder; no SDK
version metadata was fabricated. A CoreFoundation-linked Mach-O ARM64 program
was built by Chromium's bundled Linux LLVM toolchain, copied back with matching
SHA-256, and executed successfully on the Mac. A C++ runtime-host dylib was also
cross-built, copied back and loaded successfully. These validate transport and
toolchain compatibility, not a complete Chromium or MetaCodes engine SDK.

GN generation for `out/metabrowser-mac-arm64` succeeds with the real 26.2 SDK
and an explicitly selected bundled Clang path. The source archive's empty
Clang revision stamp means this toolchain must be tracked as an explicit input;
a production build must reconcile it with the pinned upstream toolchain.

`chromium/metabrowser` contains the runtime-host ABI and native side-panel
factory hook. `scripts/stage-chromium-hooks.py` stages them idempotently in the
pinned tree and adds a GN verification group. The staging script now wires the panel into window initialization; its native
label explicitly says that MetaCodes is not connected. MetaCodes runtime
implementation, page-operation adapters, actual panel content and end-to-end
acceptance are still unfinished.

Cross-host dependencies added from the pinned source DEPS:

- macOS compiler runtime SHA-256
  `3a58ee21a570b296b07560467db47ebd212133c1d406d1b0ff87030e483d8867`.
- Linux MIG CIPD instance `4wxov_ILjFdgBumBqgUgOgIcr4kcMh7i4b4oJi_cLjcC`;
  downloaded archive SHA-256 URL-safe digest matches the instance's digest.

The Mac's C lifecycle test and Zig native consumer both link to the actual
cross-built dylib. Neither invokes a model provider or claims agent execution.

Repeat the native boundary check after rebuilding on H200:

```bash
# On H200, with staged sources:
bash /data/metabrowser/project/scripts/cross-runtime-host.sh
# On the development Mac:
bash scripts/verify-returned-runtime.sh
```

`build/mac-arm64.args.gn` records the working cross-target configuration.
The native side-panel object compiled successfully and GN header checks passed
for both the hook and the browser-window startup target. The startup object also compiled successfully as Mach-O ARM64. Successful
registration has not yet been observed inside a running browser.

## 2026-10-15 Mac readiness receipt

H200 completed all 46,898 remaining Chromium app build steps, including the
final verify-libraries action. The full 733 MB app was returned to
`out/macos-arm64/Chromium.app`; its executable and framework hashes match H200.
`--version` reports Chromium 154.0.8037.97. A separate local test profile starts
a native browser process and child processes successfully. Side-panel display
has not yet been accepted inside the running app.

The complete installed MetaCodes SDK (source e55d88dade87, ABI 19, macOS ARM64)
passes its manifest file hashes. `agentcore:probe` validates all five mandatory
API tables using the supplied Zig binding, initializes/destroys a native
AgentCore runtime and links the returned browser bridge in one Zig executable.
It performs no model/provider requests. This is native integration readiness,
not proof of a browser-contained session or a completed sidebar.

```bash
zig build agentcore:probe \
  -Dagentcore-sdk="$HOME/.local/opt/metacodes/sdk/agentcore-metabrowser-e55d88da" \
  -Doptimize=ReleaseSafe
```

## 2026-10-15 native Session integration acceptance

The implemented native Views panel replaces the disconnected label. Its toolbar
entry opens alongside normal tabs and supports provider/model/key configuration,
streamed replies, multi-turn conversation, Stop and New Session. Chromium's final
incremental cross-build and native header dependency check pass. Packaging returns
the complete app, validates its engine contents, adds the pinned complete SDK and
Zig adapter, and records all 372 packaged files/symlinks. Post-launch application
hash verification passes.

Acceptance uses a clearly labelled local OpenAI SSE fixture (no paid calls):

- Native C consumer: real SDK multi-turn streaming, active abort and recreate pass.
- Native macOS accessibility driver: send/stream, second turn, Stop, recovery,
  new Session, hide/reopen cancellation and final visible demo all pass.
- Browser remains running with its native panel in front. Screenshot:
  `out/evidence/metacodes-native-sidebar.png`.
- Live image inspection confirms AgentCore loaded from the app's bundled SDK,
  rather than relying on the developer's installed SDK.

Two integration failures were fixed before acceptance: SDK execution exceeded
macOS's default 512 KiB thread stack (now 16 MiB), and SDK state was freed while a
Chromium checked pointer still held it (now cleared before free). Side-panel hide
is observed before animation instead of relying on a later visibility callback.

The Python fixture and Swift accessibility driver are development-only; the
shipped app is Chromium/C++ plus the Zig adapter and native AgentCore library.
Page-operation tools and complete agent-browser roadmap acceptance remain open.
