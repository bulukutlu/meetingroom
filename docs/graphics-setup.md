# Ubuntu 3D graphics setup

The screenshot shows Chrome failing to create a WebGL context. It does not establish whether acceleration is disabled, a driver is blocked, or a VM/remote session lacks graphics support. The current [Three.js renderer requires WebGL 2](https://threejs.org/docs/pages/WebGLRenderer.html); Python packages alone cannot establish browser GPU support.

## Try this on Ubuntu now

1. In Chrome, open Settings → System and enable **Use graphics acceleration when available**, then relaunch Chrome. Check `chrome://gpu`, particularly WebGL2 and **Problems Detected**. Browser graphics settings and driver stability affect WebGL availability, as described in [Google's graphics troubleshooting guidance](https://support.google.com/meet/answer/9302964?hl=en).
2. Apply Ubuntu updates. For NVIDIA, open **Software & Updates → Additional Drivers**, choose the recommended tested driver, apply it and reboot. Use [Ubuntu's driver instructions](https://ubuntu.com/desktop/docs/en/latest/how-to/graphics/install-nvidia-drivers/).
3. For an Intel/AMD Mesa desktop with missing system graphics packages, install the runtime libraries and diagnostic tools:

```bash
sudo apt update
sudo apt install libgl1 libegl1 libgl1-mesa-dri libegl-mesa0 mesa-utils
glxinfo -B
```

Ubuntu supplies the [Mesa DRI modules](https://packages.ubuntu.com/noble/libgl1-mesa-dri). `glxinfo` tests desktop OpenGL, rather than the browser's WebGL 2 support. NVIDIA installations should follow Ubuntu's driver manager instead of replacing drivers blindly.

If Ubuntu is in a VM, enable the VM's 3D acceleration and install its guest graphics drivers. If using a remote desktop, compare with the browser running on the local graphical desktop. Some virtual/remote graphics devices cannot expose the capabilities this renderer needs.

## New first-start behavior

- The initial installer prints read-only graphics setup hints before creating the Python environment. Later program starts also print the graphics requirement.
- Both the corridor and room check the actual browser before entering 3D: context creation, shader compilation/linking, an 8-bit stencil buffer, drawing and pixel readback.
- On failure, the app shows repair steps and a **Check again** button instead of silently continuing with a flat interface. Subsequent renderer startup errors show the same help.
- **Download diagnostics** exports the result and browser version. The private app access token and full URL are omitted.
- `./run.sh doctor` provides Linux library/display checks once the updated source is installed. It does not claim that desktop libraries prove browser compatibility.

The checks do not modify browser settings, install system drivers or bypass the browser's GPU protections.

## Portable test

Open **graphics-check.html** in the Ubuntu browser to run the same test without changing the installed Meeting Room version. It works as a standalone file and needs no Python service. A pass on the Mac does not establish that Ubuntu passes.

## Validation

64 Python tests and all six Node scripts passed, including the new graphics tests. Tests cover missing WebGL 2, shader/link/stencil/draw failures, cleanup, the retry gate, safe error rendering and token-free diagnostics. Shell and generated-page syntax checks passed. Actual Ubuntu hardware/browser validation remains outstanding.

The startup behavior changes after installing the updated source and restarting the app. The repair instructions and portable test can be used independently of the installed app version.
