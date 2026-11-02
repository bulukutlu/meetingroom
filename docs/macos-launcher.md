# Meeting Room for the Mac Dock

**The app is built:** `Meeting Room.app` in the project folder.

1. Find the app in that project folder and double-click it.
2. It opens Meeting Room in your usual browser; no Terminal window is needed.
3. Drag the app icon to the Dock to keep it there. You can also move the launcher to Applications.

The launcher reuses the project's Python environment, speech models and meeting records. It adds about 220 KB rather than bundling another copy of the large dependencies. Keep the original project folder in place; rebuild the launcher if you move that folder.

Clicking the Dock icon reopens the browser interface. The launcher can attach to an existing local server; the currently running server has been registered privately for this purpose, without restarting this meeting. On later launches it starts the server itself if needed. Its Quit command uses the app's existing save-and-close route.

Validation: the native Swift executable compiled, passed its URL-routing self-test, and the bundle's local signature and Info.plist were verified. Python tests cover private readiness-state files, startup readiness, startup failure and cleanup. Opening the GUI and pinning it to the Dock still need a manual check on the Mac.

To rebuild after moving the project: `.venv/bin/python tools/build_macos_app.py --replace`.

The launcher is built for this Mac and signed locally, rather than packaged for distribution to other machines. Logs are kept privately in `.app-launcher.log` in the project folder.

The launcher follows Apple's [application-bundle structure](https://developer.apple.com/library/archive/documentation/CoreFoundation/Conceptual/CFBundles/BundleTypes/BundleTypes.html). Apple's [Dock guide](https://support.apple.com/en-gb/guide/mac-help/mh35859/mac) describes adding and removing app icons.
