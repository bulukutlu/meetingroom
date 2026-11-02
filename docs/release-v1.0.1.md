# Meeting Room v1.0.1

This patch adds first-start graphics checks and Ubuntu repair guidance, and keeps new meeting workspaces inside the cloned repository by default.

## Graphics startup

The corridor and meeting room test browser WebGL 2 context creation, shaders, stencil support and actual drawing before entering 3D. A failure shows repair instructions and a retry button. Diagnostic downloads omit the private app access token.

Use `./run.sh doctor` for read-only Linux desktop/library hints. [Ubuntu setup instructions](graphics-setup.md) explain browser acceleration, drivers, Mesa packages and VM/remote-desktop limitations. The [standalone graphics test](graphics-check.html) can also run directly in the Ubuntu browser.

These checks help diagnose the browser/driver configuration; they do not install drivers or change browser settings automatically.

## Existing installations: workspace location

The new default is `workspace/` inside the repository. Demo data goes into `workspace/demo/`. Existing data in `~/MeetingRoom` is retained; it is not automatically migrated. Without a copy, the default workspace initially has no old meetings or Kokoro models.

Save and close the app before upgrading. To preserve previous data with the new default, copy the contents of `~/MeetingRoom` into `workspace/` using your file manager, or run the following from the repository folder:

```bash
mkdir -p workspace
rsync -a --ignore-existing "$HOME/MeetingRoom/" workspace/
```

This keeps the original copy and avoids overwriting files already present in the new workspace. An explicit absolute `workspace:` setting is still supported if you prefer the previous location.

Whisper weights still use Hugging Face's standard cache, usually `~/.cache/huggingface`; they are not moved or downloaded again by this patch. Claude/Codex authentication and native CLI session storage also remain managed by those tools.

## Upgrade

After saving and closing the app and handling the workspace note above:

```bash
git pull --ff-only
git describe --tags --always
./run.sh
```

For the macOS Dock launcher, rebuild its version metadata with `.venv/bin/python tools/build_macos_app.py --replace` if desired. It continues to reuse the project rather than duplicating the environment and models.

The patch was validated with the full Python suite and all six Node test scripts. Actual Ubuntu GPU/driver behavior remains dependent on the machine and browser.
