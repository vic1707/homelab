Needs `adb`.

From factory reset, enable adb, connect manually and run install.

The script installs and configures the apps, restores Key Mapper mappings,
sets Arc as the home launcher, disables location and camera/microphone access,
turns off developer options and ADB, and reboots the TV.

## App updates

Install the APK versions pinned in `settings.yml` without reconfiguring or
rebooting the TV:

```sh
./devices/tv/install.py update-apps
```

## Mappings

Save the readable repository copy:

   ```sh
   ./devices/tv/install.py save-mappings
   ```

## Manual setup

### Input menu

Use the TCL input menu editor to keep **Home** and **AirPlay** forced, keep all
HDMI inputs always visible, and hide **TV**, **Media Player**, **Multi Visual**,
and **Recent Apps**. Do not disable the corresponding TCL packages; Miracast
and Media Center are still needed.

### Arc Launcher

Configure Arc manually after installation. The desired setup is a black
background, purple highlight, the required focus/animation toggles enabled,
most apps hidden, and only the selected favorites shown. Arc stores these
preferences and its app/category layout in private app data, so they are not
reproducible with ADB settings commands.

### Picture Settings

The script cannot configure picture settings. TCL stores them through its PQ
service per input and signal type. Configure SDR and HDR separately while
active: Filmmaker mode, brightness `100`, and adaptive/dynamic brightness off.

## Known issue
Arc 1.0.6 has an upstream focus-rendering issue. Keep **Show focus borders**
and **App card highlight animation** enabled under **Interface > Appearance**.

## Recovery

If the stock launcher or Key Mapper becomes unusable:

```sh
adb shell pm enable com.google.android.apps.tv.launcherx
adb shell pm enable com.google.android.tungsten.setupwraith
adb shell input keyevent KEYCODE_HOME
```

To re-enable the final launcher state, run the install script again after
confirming `remaps.json` is current.
