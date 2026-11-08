#!/usr/bin/env uv run --project ../.. python
"""Install and configure the TCL TV over ADB."""

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
CONFIG = ROOT / "settings.yml"
DOWNLOADS = ROOT / ".download"
TV = os.environ.get("TV", "TV.lan:5555")
HOME_INTENT = ("-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME")


def log(message: str) -> None:
    print(f"[tv] {message}", flush=True)


def config() -> dict:
    data = yaml.safe_load(CONFIG.read_text())
    data["launcher"]["package"] = data["packages"]["github"]["launcher"]["package"]
    return data


def run(*args: str, capture: bool = False, check: bool = True) -> str:
    result = subprocess.run(
        ["adb", "-s", TV, *args], check=check, text=True, capture_output=capture
    )
    return result.stdout.strip() if capture else ""


def shell(*args: str, capture: bool = False, check: bool = True) -> str:
    return run("shell", *args, capture=capture, check=check)


def setting(namespace: str, key: str, value: str) -> None:
    shell("settings", "put", namespace, key, value)


def download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url) as source, target.open("wb") as destination:
        shutil.copyfileobj(source, destination)


def configure(data: dict) -> None:
    setting("global", "device_name", data["name"])
    shell("setprop", "persist.sys.tvname", data["name"])
    setting(
        "secure", "tv_input_custom_labels", ":".join(data["tv_input_custom_labels"])
    )
    for namespace, values in data["settings"].items():
        for key, value in values.items():
            setting(namespace, key, value)


def debloat(data: dict) -> None:
    packages = data["packages"]
    for package in packages["disabled"]:
        log(f"disable {package}")
        shell("pm", "disable-user", "--user", "0", package, check=False)
    for package in packages["removed"]:
        log(f"remove {package}")
        shell("pm", "uninstall", "--user", "0", package, check=False)
    # Android writes package state about ten seconds after a change; a reboot before that loses it.
    shell("sync")
    installed = shell("pm", "list", "packages", capture=True).splitlines()
    enabled = shell("pm", "list", "packages", "-e", capture=True).splitlines()
    left = [p for p in packages["removed"] if f"package:{p}" in installed]
    left += [p for p in packages["disabled"] if f"package:{p}" in enabled]
    if left:
        log(f"still present: {', '.join(left)}")


# Launcher


def push_theme(launcher: dict) -> None:
    package = launcher["package"]
    files = f"/sdcard/Android/data/{package}/files"
    uri = f"content://{package}.theme"
    staging = DOWNLOADS / "theme"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "config.json").write_text(json.dumps(launcher["theme"], indent=2))
    # A new revision makes the launcher drop on-TV layout choices in favour of the theme.
    (staging / "theme_revision").write_text(uuid.uuid4().hex)
    for name in ("config.json", "theme_revision"):
        staged = f"/data/local/tmp/cyt-theme-{name}"
        run("push", str(staging / name), staged, capture=True)
        # Only through the launcher's provider: a file the shell copies into Android/data stays
        # shell-owned and the launcher cannot read it (EACCES).
        for _ in range(5):
            output = shell(
                f"rm -f {files}/{name} 2>/dev/null; "
                f"content write --uri {uri}/{name} < {staged} 2>&1; ls -n {files}/{name} 2>&1",
                capture=True,
                # The first write right after an install can fail; retry instead of stopping.
                check=False,
            )
            if "Error" not in output and "No such file" not in output:
                break
            time.sleep(1)
        else:
            raise SystemExit(f"theme push of {name} failed: {output}")
        shell("rm", "-f", staged)


def allow_auto_start(package: str) -> None:
    # TCL's TclAppBoot refuses to start a stopped app's provider or bind its accessibility
    # service without this app-op, and only writes it to disk on write-settings.
    for op in ("AUTO_START", "APP_AUTO_START"):
        shell("cmd", "appops", "set", package, op, "allow", capture=True, check=False)
    shell("appops", "write-settings", capture=True, check=False)


def enable_key_services(launcher: dict) -> None:
    package = launcher["package"]
    allow_auto_start(package)
    current = shell(
        "settings", "get", "secure", "enabled_accessibility_services", capture=True
    )
    others = [
        s for s in current.split(":")
        if s and s != "null" and not s.startswith(f"{package}/")
    ]
    wanted = [f"{package}/.{name}" for name in launcher["key_services"]]
    # A service refused while its APK was replaced only binds again once the list changes.
    shell("settings put secure enabled_accessibility_services ''")
    setting("secure", "accessibility_enabled", "0")
    time.sleep(1)
    setting("secure", "enabled_accessibility_services", ":".join([*others, *wanted]))
    setting("secure", "accessibility_enabled", "1")
    shell("pm", "revoke", package, "android.permission.WRITE_SECURE_SETTINGS", check=False)
    for _ in range(20):
        bound = shell("dumpsys", "accessibility", capture=True)
        if all(f"{name}" in bound.split("Bound services", 1)[-1] for name in launcher["key_services"]):
            return
        time.sleep(0.5)
    log("warning: key services enabled but not bound yet")


def set_home(launcher: dict) -> None:
    package = launcher["package"]
    shell("cmd", "role", "add-role-holder", "--user", "0", "android.app.role.HOME", package, "0")
    shell("cmd", "package", "set-home-activity", "--user", "0", f"{package}/.MainActivity")


def verify_home(launcher: dict) -> None:
    package = launcher["package"]
    home = shell("cmd", "package", "resolve-activity", "--brief", *HOME_INTENT, capture=True)
    if home.splitlines()[-1] != f"{package}/.MainActivity":
        raise SystemExit(f"failed to set home launcher: {home}")
    # resolve-activity can name the launcher while Home still opens something else.
    shell("input", "keyevent", "KEYCODE_HOME")
    time.sleep(2)
    focus = shell("dumpsys", "activity", "activities", capture=True)
    focused = next((l for l in focus.splitlines() if "mFocusedApp" in l), "")
    if package not in focused:
        raise SystemExit(f"Home did not open the launcher: {focused.strip()}")


def restart_launcher(launcher: dict) -> None:
    shell("am", "force-stop", launcher["package"])
    enable_key_services(launcher)
    shell("input", "keyevent", "KEYCODE_HOME")


def configure_launcher(launcher: dict) -> None:
    allow_auto_start(launcher["package"])
    push_theme(launcher)
    set_home(launcher)


# Apps


def download_store(app: dict, destination: Path, source: str) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    cached = sorted(destination.rglob("*.apk"))
    if not cached:
        if source == "fdroid":
            command = [
                "apkeep", "-a", f"{app['package']}@{app['version']}", "-d", "f-droid"
            ]
            if abi := app.get("abi"):
                command.extend(("-o", f"arch={abi}"))
            command.append(str(destination))
        else:
            # ponytail: APKMirror versions refresh the cache; fetch the current TV build.
            command = [
                "goopdl", "download", app["package"], "--arch", "tv", "--splits", "--no-extras",
                "--integrity-manifest", str(destination / "integrity.json"),
                "--output", str(destination),
            ]
        subprocess.run(command, check=True)
        cached = sorted(destination.rglob("*.apk"))
    if source == "fdroid" and (abi := app.get("abi")):
        # ponytail: apkeep's F-Droid v2 index ignores arch; reject mismatched APKs.
        for apk in cached:
            with zipfile.ZipFile(apk) as archive:
                if not any(name.startswith(f"lib/{abi}/") for name in archive.namelist()):
                    raise SystemExit(f"{apk} is not built for {abi}")
    return cached


def install_apps(data: dict) -> None:
    packages = data["packages"]
    github_apps = packages["github"]

    DOWNLOADS.mkdir(exist_ok=True)
    store_apks = {}
    for source in ("playstore", "fdroid"):
        for name, app in (packages.get(source) or {}).items():
            log(f"prepare {name}")
            store_apks[name] = download_store(
                app, DOWNLOADS / ("goopdl" if source == "playstore" else source)
                / name / app["version"], source
            )
    for name, apks in store_apks.items():
        if not apks:
            raise SystemExit(f"no {name} APKs downloaded")
        log(f"{name}: {len(apks)} APK file(s) ready")

    github_apks = []
    for name, app in github_apps.items():
        target = DOWNLOADS / f"{name}.apk"
        version = app["version"]
        tag = app.get("release_tag", "{version}").format(version=version)
        asset = app["asset"].format(**app)
        log(f"download {name}")
        download(
            f"https://github.com/{app['repository']}/releases/download/{tag}/{asset}",
            target,
        )
        if app.get("attested"):
            # Build provenance: the APK came from that repository's workflow, unmodified.
            subprocess.run(
                ["gh", "attestation", "verify", str(target), "--repo", app["repository"]],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        github_apks.append(target)

    for apk in github_apks:
        log(f"install {apk.stem}")
        run("install", "-r", str(apk))
    for name, app_apks in store_apks.items():
        log(f"install {name} ({len(app_apks)} APK file(s))")
        if len(app_apks) == 1:
            run("install", "-r", str(app_apks[0]))
        else:
            run(
                "install-multiple",
                "-r",
                "-i",
                "com.android.vending",
                *(str(apk) for apk in app_apks),
            )


# Commands


def finish(data: dict) -> None:
    configure(data)
    shell("cmd", "location", "set-location-enabled", "false", "--user", "0")
    shell("cmd", "sensor_privacy", "enable", "0", "microphone")
    shell("cmd", "sensor_privacy", "enable", "0", "camera")
    log("disable ADB and reboot")
    subprocess.run(
        [
            "adb",
            "-s",
            TV,
            "shell",
            "sh",
            "-c",
            # Detached: turning ADB off kills this shell, and a `reboot` chained after it with it.
            "sync; setsid sh -c 'sleep 2; settings put global development_settings_enabled 0;"
            " settings put global adb_enabled 0; sleep 1; reboot' </dev/null >/dev/null 2>&1 &",
        ],
        check=False,
    )


def install() -> None:
    data = config()
    install_apps(data)
    configure_launcher(data["launcher"])
    debloat(data)
    enable_key_services(data["launcher"])
    verify_home(data["launcher"])
    finish(data)


def update_apps() -> None:
    data = config()
    install_apps(data)
    configure_launcher(data["launcher"])
    restart_launcher(data["launcher"])
    verify_home(data["launcher"])


def theme() -> None:
    launcher = config()["launcher"]
    push_theme(launcher)
    restart_launcher(launcher)


def main() -> None:
    commands = {
        "install": install,
        "update-apps": update_apps,
        "debloat": lambda: debloat(config()),
        "theme": theme,
    }
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="install", choices=commands)
    args = parser.parse_args()
    subprocess.run(["adb", "connect", TV], check=True, stdout=subprocess.DEVNULL)
    run("wait-for-device")
    commands[args.command]()


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as error:
        raise SystemExit(f"missing command or file: {error}")
