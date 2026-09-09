# Trackpad pinch zoom

The Cocoa runtime converts macOS magnification into two symmetric contacts on a
`virtio-pinch-pci` touchpad. This provides continuous pinch zoom to Wayland apps
that support gestures. The existing tablet handles pointer movement, clicks,
and scrolling. Rotation and other trackpad gestures are not forwarded.

Contact spacing is bounded per gesture; lift and pinch again to continue beyond
those bounds. Cancellation, focus loss, and VM state changes clear the gesture.
The device disables tapping and disable-while-typing so synthetic contacts do
not cause clicks or get suppressed after keyboard input.

## Existing guests

New factory guests include the device settings. For an existing Lua-based
Omarchy guest, run this inside its desktop as your normal user:

```sh
python3 ~/src/try-omarchy/guest/scripts/upgrade-pinch-input.py
```

The migration preserves existing settings, saves a backup beside
`~/.config/hypr/input.lua`, and appends a self-contained device override. It
reloads Hyprland and restores the original file if validation fails. Re-running
is safe; edited managed blocks and symlinked files require manual review.
Configuration refreshes that replace `input.lua` may require another migration.

Shut down the guest and reopen its saved VM with the updated Mac app. A guest
reboot alone cannot add the new virtual device. From a development checkout,
`./macos/open-qemu-gpu.sh` opens the built app in persistent mode.

Check `hyprctl devices` for `qemu-virtio-pinch-touchpad` and confirm
`hyprctl configerrors` is empty before testing pinch zoom.

## Validation and limitations

Chromium pinch zoom was confirmed on new and existing persistent guests.
Intermittent libinput touch-jump detection remains unresolved. Firefox has not
been validated.

`make test` covers the production gesture model and migration. An optional Linux
ABI test checks the actual device capabilities, contact frames, and button routing:

```sh
QEMU_PINCH_TEST_BINARY=/absolute/path/to/patched/qemu-system-x86_64 \
  python3 macos/Tests/test-virtio-pinch.py
```

Apple Silicon integration checks should cover pinch in both directions, repeated
and cancelled gestures, focus switching, ordinary pointer input, fullscreen,
sleep/wake, and saved guests. Model and ABI tests do not exercise AppKit delivery
or live libinput recognition.
