WIKCIA STUDIO - WINDOWS 11 x64

INSTALL
1. Copy this entire folder/ZIP to the other computer.
2. Right-click the ZIP > Extract All.
3. Open the extracted Wikcia-Windows11 folder.
4. Double-click INSTALL-WIKCIA.cmd. Keep the window open until it finishes.
5. Open Wikcia Studio or Wikcia CLI from the Desktop shortcuts.

Read FIRST-RUN.txt for the included panels and provider setup. The interface
and module coverage is recorded in FEATURES.json and checked during packaging.
All four bundled Desktop packages are enabled by default on first launch.
The Desktop and Agent switches under Tools > Plugins remain separate; setup
does not copy sender UI preferences or override explicit recipient choices.

The launcher works both inside the complete distribution and at the outer root
of the maintained source-package layout. It resolves bundle\Wikcia-Windows11
without requiring Python or any developer tools on PATH. A genuinely missing
payload is reported with the checked paths, not a misleading unzip error.

The default installs the core, product configuration, all 25 application recipes,
Chromium for the research browsers and all manifest-listed model assets.
--check-only is read-only discovery. --stage-only copies payloads but does NOT
install a working runtime. --core-only and --apps ID are reduced-scope operations.
--skip-models explicitly omits large model downloads and records that scope.
Do not confuse a successful check/stage operation with completed installation.

Setup detects existing integrated applications and reuses their paths. Missing
components are downloaded from their recorded upstream sources. Re-running is
supported; interrupted/failed components are reported instead of silently skipped.
A first installation can download multiple GB. Internet is required. Windows may
request normal Windows approval where needed. Fresh Ollama, Blender and Audacity
installs use pinned portable upstream packages; winget, Microsoft Store, WSL and
Docker are not prerequisites. Do not
disable antivirus, SmartScreen, execution policy or Windows security protections.

INSTALLED LOCATION
%LOCALAPPDATA%\WikciaStudio

The installation is separate from existing Hermes. It does not uninstall Hermes,
replace its CLI command, or copy the sender's accounts, credentials, history,
memories, customer data or private configuration. Existing third-party software
is detected, not upgraded without need. Open a new terminal for the wikcia command.
Use your OWN model-provider accounts in Wikcia's setup/settings. No paid service,
subscription, overage, or inference is enabled by this installer.

CONTENTS
Native Wikcia Studio Desktop; Wikcia CLI/core; Application Hub; Prime; research,
CRM and studio plugins; product workflow skills; pinned free-software recipes for
ArtCraft Launcher and seven Craft applications, research/document/workflow Python
tools, SearXNG, ComfyUI source/runtime, OmniRoute, FreeLLMAPI, Promptfoo, Ollama,
Blender and Audacity. Python/Node/Git/FFmpeg/browser and computer-use prerequisites
are managed by the bundled core's pinned package manager.

Model assets are now part of the default full installation. Setup reuses or
retrieves both installed Qwen models, the SD1.5 checkpoint and all installed
translation language packages, and verifies their recorded content. If none are
present, model files alone occupy about 40 GiB, plus application/dependency/cache
space. Downloads may take hours on a slow connection; rerun after interruptions.
External services still require the recipient's OWN account authentication.
ArchiveBox and catalog-only applications absent from the source system are not
misrepresented as installed components.
The full source repositories/versions used by each component are recorded in
manifest.json. Source-based components fetch exact recorded Git commits; Python
and Node packages use the recorded package versions.

REPORTS AND RECOVERY
%LOCALAPPDATA%\WikciaStudio\installation-report.json
%LOCALAPPDATA%\WikciaStudio\component-progress.json
%LOCALAPPDATA%\WikciaStudio\install-logs\

If a download fails, close Wikcia and rerun INSTALL-WIKCIA.cmd from this extracted
folder. A partial
installation is explicitly reported; the software is not claimed fully functional
merely because files were installed. Keep this installer folder for repairs.
Do not use upstream Hermes Update/Repair/Uninstall to manage this customized
installation. Use a new Wikcia bundle for updates. Your original Hermes remains
independent. This is an unsigned internal transfer build, not a signed commercial
release or proof of clean-machine acceptance on your specific computer.

FULL PRODUCT CONTENT
This build includes the maintained Design Station and website generator, the
LPX swarm source, all agent role cards and installed skill categories, and the
CRM engine including browser worker and SQL migrations. The CRM and Maps native
panels are repaired and validated; a panel syntax error stops full installation
rather than being silently quarantined. Existing recipient-owned persona and
credentials are preserved; changed managed code is backed up on upgrade.

FOUNDATION AND LICENSES
Wikcia is built on customized Hermes Agent by Nous Research. Upstream MIT notices,
Electron/Chromium notices and bundled dependency licenses are preserved. Extra
software is downloaded from its original distributor under its own license.
