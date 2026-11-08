Needs `adb`, and an authenticated `gh` to verify the launcher's build attestation.

From factory reset (Basic TV setup, no Google account), enable ADB, connect
manually and run install:

```sh
./devices/tv/install.py
```

The script installs the apps and the
[Clean Your TV](https://github.com/Gathin23/cleanyourtv) launcher as Home with
its remote-button helper, removes or disables the packages listed in
`settings.yml`, applies the TV settings, disables location and
camera/microphone access, turns off developer options and ADB, and reboots.

Afterwards, revoke the USB debugging authorisations in Developer options if
you re-enabled it, and check that ADB is closed.

## Commands

| Command       | What it does                                                          |
| ------------- | --------------------------------------------------------------------- |
| `install`     | Everything above (default)                                            |
| `update-apps` | Install the current app versions and launcher, no reboot              |
| `debloat`     | Re-apply the `disabled`/`removed` lists, e.g. after a firmware update |
| `theme`       | Push `launcher.theme` from `settings.yml` and restart Home            |

Twitch uses mise-managed `goopdl` (installed through uv) with an
Android TV profile and anonymous Aurora authentication; no personal Google
credentials are needed. APKMirror versions refresh their download cache rather
than pinning the Play build. A `packages.fdroid` entry is downloaded with
`apkeep` at its pinned F-Droid version.

## Launcher

Upstream publishes the launcher as source only.
[vic1707/cleanyourtv-launcher](https://github.com/vic1707/cleanyourtv-launcher)
builds each upstream tag unmodified, signs it and attests its build
provenance. It is installed like the other GitHub apps
(`packages.github.launcher`); `attested: true` makes `install.py` run
`gh attestation verify` on it before installing. `launcher:` only holds its
Home-screen configuration.
The signing key is backed up in `.secrets/devices/tv.yml`.

Its configuration lives in `launcher.theme`; every key is documented in the
upstream `themes/README.md`. Change it and run `install.py theme`:

- `dock_apps`: dock order. `columns`: tiles per row.
- `hidden_apps`: packages never shown as tiles.
- `app_keys`: remote buttons, as `"<keycode>:<package>"`,
  `"<keycode>:input:<tv input id>"` or `"scan:<scancode>:<package>"`. Read a
  button's codes with `adb shell getevent -lt` or from `logcat`
  (`handleKeyBeforeQueueing`).
- `wallpaper`, `background_color`: see upstream `themes/README.md`.

While `HomeKeyService` is bound, holding Volume moves one step per press: any
key-filtering accessibility service does that on this firmware.

## Debloat

`settings.yml` lists the packages to disable and to remove for user 0, with
the ones kept on purpose in a comment above them. Firmware updates come
through `com.tcl.ttvs`, which is kept for that reason; it also carries TCL's BI
telemetry, which is blocked in DNS instead. Run `install.py debloat` after a
firmware update in case it brought packages back.

Re-enable or bring back a package:

```sh
adb shell pm enable <package>                      # disabled
adb shell cmd package install-existing <package>   # removed
```

## Manual setup

### Input menu

Use the TCL input menu editor to keep **Home** and **AirPlay** forced, keep all
HDMI inputs always visible, and hide **TV**, **Media Player**, **Multi Visual**,
and **Recent Apps**, and remove the promoted apps (Plex, Pluto TV, ...): they
are entries of the panel itself, not installed apps, and return after a reset.
Not scriptable: the panel keeps its layout in its own data, behind a provider
(`content://com.tcl.suspension/source_order`) the ADB shell may not read. Do
not disable `com.tcl.suspension` or `com.tcl.interactive`: they run the Input
button's panel.

### Picture Settings

The script cannot configure picture settings. TCL stores them through its PQ
service per input and signal type. Configure SDR and HDR separately while
active: Filmmaker mode, brightness `100`, and adaptive/dynamic brightness off.
