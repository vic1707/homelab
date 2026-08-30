#!/usr/bin/env uv run --project ../.. python
"""Install and configure the TCL TV over ADB."""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
CONFIG = ROOT / "settings.yml"
FILES = ROOT / "files"
MAPPINGS = FILES / "remaps.json"
REMOTE_BACKUP = "/sdcard/Download/key_mapper.zip"
BACKUP_URI = (
    "content://dev.dworks.apps.anexplorer.externalstorage.documents/document/"
    "primary%3ADownload%2Fkey_mapper.zip"
)
TV = os.environ.get("TV", "TV.lan:5555")


def log(message: str) -> None:
    print(f"[tv] {message}", flush=True)


def config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["adb", "-s", TV, *args], check=True, text=True, capture_output=capture
    )
    return result.stdout.strip() if capture else ""


def shell(*args: str, capture: bool = False) -> str:
    return run("shell", *args, capture=capture)


def setting(namespace: str, key: str, value: str) -> None:
    shell("settings", "put", namespace, key, value)


def ui_dump() -> ET.Element:
    shell("uiautomator", "dump", "/sdcard/install-ui.xml")
    return ET.fromstring(shell("cat", "/sdcard/install-ui.xml", capture=True))


def ui_matches(
    node: ET.Element, *, text: str | None = None, description: str | None = None
) -> bool:
    """Return whether a node matches a supplied label.

    >>> node = ET.fromstring('<node text="Settings" />')
    >>> ui_matches(node, text="Settings")
    True
    >>> ui_matches(node, description="More")
    False
    """
    if text is None and description is None:
        raise ValueError("text or description is required")
    return (text is not None and node.get("text") == text) or (
        description is not None and node.get("content-desc") == description
    )


def ui_tap(*, text: str | None = None, description: str | None = None) -> None:
    for _ in range(20):
        root = ui_dump()
        parents = {child: parent for parent in root.iter() for child in parent}
        for node in root.iter():
            if not ui_matches(node, text=text, description=description):
                continue
            target = node
            while target is not None and target.get("clickable") != "true":
                target = parents.get(target)
            if target is None:
                target = node
            left, top, right, bottom = (
                int(value)
                for value in target.get("bounds", "")
                .replace("][", ",")
                .replace("[", "")
                .replace("]", "")
                .split(",")
            )
            shell("input", "tap", str((left + right) // 2), str((top + bottom) // 2))
            return
        time.sleep(0.25)
    wanted = text or description
    raise SystemExit(f"UI element not found: {wanted}")


def ui_has(*, text: str | None = None, description: str | None = None) -> bool:
    root = ui_dump()
    return any(
        ui_matches(node, text=text, description=description) for node in root.iter()
    )


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


def enable_accessibility(data: dict) -> None:
    keymapper = data["packages"]["github"]["keymapper"]["package"]
    service = f"{keymapper}/.system.accessibility.MyAccessibilityService"
    current = shell(
        "settings", "get", "secure", "enabled_accessibility_services", capture=True
    )
    services = [] if current in ("", "null") else current.split(":")
    if service not in services:
        setting(
            "secure", "enabled_accessibility_services", ":".join([*services, service])
        )
    setting("secure", "accessibility_enabled", "1")
    shell("cmd", "appops", "set", keymapper, "APP_AUTO_START", "allow")
    shell("dumpsys", "deviceidle", "whitelist", f"+{keymapper}")
    shell("am", "set-inactive", keymapper, "false")


def finish(data: dict) -> None:
    launcher = data["packages"]["github"]["arclauncher"]["package"]
    configure(data)
    enable_accessibility(data)
    shell(
        "cmd",
        "role",
        "add-role-holder",
        "--user",
        "0",
        "android.app.role.HOME",
        launcher,
        "0",
    )
    shell(
        "cmd",
        "package",
        "set-home-activity",
        "--user",
        "0",
        f"{launcher}/.MainActivity",
    )
    for package in data["packages"]["disabled"]:
        shell("pm", "disable-user", "--user", "0", package)
    home = shell(
        "cmd", "package", "resolve-activity", "--brief",
        "-a", "android.intent.action.MAIN",
        "-c", "android.intent.category.HOME",
        capture=True,
    )
    if home.splitlines()[-1] != f"{launcher}/.MainActivity":
        raise SystemExit(f"failed to set home launcher: {home}")
    shell("cmd", "location", "set-location-enabled", "false", "--user", "0")
    shell("cmd", "sensor_privacy", "enable", "0", "microphone")
    shell("cmd", "sensor_privacy", "enable", "0", "camera")
    subprocess.run(
        [
            "adb",
            "-s",
            TV,
            "shell",
            "sh",
            "-c",
            "settings put global development_settings_enabled 0 && settings put global adb_enabled 0 && reboot",
        ],
        check=False,
    )


def restore() -> None:
    temporary = ROOT / ".download"
    temporary.mkdir(exist_ok=True)
    backup = temporary / "key_mapper.zip"
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(MAPPINGS, "data.json")
    run("push", str(backup), REMOTE_BACKUP)
    shell(
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        BACKUP_URI,
        "-t",
        "application/zip",
        "-n",
        "io.github.sds100.keymapper/.base.backup.RestoreKeyMapsActivity",
    )
    time.sleep(2)
    ui_tap(text="Replace")
    print("Key Mapper mappings restored")


def setup_automatic_backup(data: dict) -> None:
    keymapper = data["packages"]["github"]["keymapper"]["package"]
    anexplorer = data["packages"]["apkeep"]["anexplorer"]["package"]
    log("configure Key Mapper automatic backup")
    shell("rm", "-f", REMOTE_BACKUP)
    shell("appops", "set", anexplorer, "MANAGE_EXTERNAL_STORAGE", "allow")
    shell("input", "keyevent", "KEYCODE_BACK")
    shell("am", "force-stop", keymapper)
    log("warm AnExplorer")
    shell(
        "am", "start", "-a", "android.intent.action.MAIN",
        "-c", "android.intent.category.LEANBACK_LAUNCHER",
        "-n", f"{anexplorer}/.DocumentsActivity",
    )
    for _ in range(20):
        if ui_has(text="Downloads"):
            break
        time.sleep(0.25)
    shell("am", "start", "-n", f"{keymapper}/.MainActivity")
    time.sleep(2)
    if ui_has(text="OK"):
        log("dismiss Key Mapper dialog")
        ui_tap(text="OK")
        time.sleep(0.5)
    log("open Key Mapper settings")
    ui_tap(description="More")
    ui_tap(text="Settings")
    for _ in range(5):
        if ui_has(text="Change automatic backup location") or ui_has(
            text="Turn on automatic backup"
        ):
            break
        shell("input", "swipe", "960", "850", "960", "300", "500")
        time.sleep(0.25)
    ui_tap(text="Change automatic backup location") if ui_has(
        text="Change automatic backup location"
    ) else ui_tap(text="Turn on automatic backup")
    time.sleep(0.5)
    if ui_has(text="Change"):
        ui_tap(text="Change")
    time.sleep(1)
    if ui_has(text="AnExplorer"):
        ui_tap(text="AnExplorer")
    if ui_has(text="Always"):
        ui_tap(text="Always")
    ui_tap(text="Download") if ui_has(text="Download") else ui_tap(text="Downloads")
    ui_tap(description="Save")
    time.sleep(2)
    log("Key Mapper automatic backup configured")


def download_apkeep(app: dict, destination: Path) -> list[Path]:
    apkeep = shutil.which("apkeep")
    if apkeep is None:
        raise SystemExit("apkeep is required to download APKs")
    destination.mkdir(parents=True, exist_ok=True)
    for xapk in destination.glob("*.xapk"):
        with zipfile.ZipFile(xapk) as archive:
            for name in archive.namelist():
                if name.endswith(".apk"):
                    archive.extract(name, destination)
    cached = sorted(destination.rglob("*.apk"))
    if cached:
        return cached
    version = app["version"].replace("-", ".")
    package = f"{app['package']}@{version}"
    command = [apkeep, "-a", package]
    if abi := app.get("abi"):
        command.extend(("-o", f"arch={abi}"))
    command.extend(shlex.split(os.environ.get("APKEEP_ARGS", "")))
    command.append(str(destination))
    subprocess.run(command, check=True)
    for xapk in destination.glob("*.xapk"):
        with zipfile.ZipFile(xapk) as archive:
            for name in archive.namelist():
                if name.endswith(".apk"):
                    archive.extract(name, destination)
    return sorted(destination.rglob("*.apk"))


def install_apps(data: dict) -> None:
    packages = data["packages"]
    github_apps = packages["github"]
    apkeep_apps = packages["apkeep"]

    temporary = ROOT / ".download"
    temporary.mkdir(exist_ok=True)
    apkeep_apks = {}
    for name, app in apkeep_apps.items():
        log(f"prepare {name}")
        apkeep_apks[name] = download_apkeep(
            app, temporary / name / app["version"]
        )
    for name, apks in apkeep_apks.items():
        if not apks:
            raise SystemExit(f"no {name} APKs downloaded")
        log(f"{name}: {len(apks)} APK file(s) ready")

    github_apks = []
    for name, app in github_apps.items():
        target = temporary / f"{name}.apk"
        version = app["version"]
        tag = app.get("release_tag", "{version}").format(version=version)
        asset = app["asset"].format(**app)
        log(f"download {name}")
        download(
            f"https://github.com/{app['repository']}/releases/download/{tag}/{asset}",
            target,
        )
        github_apks.append(target)

    for apk in github_apks:
        log(f"install {apk.stem}")
        run("install", "-r", str(apk))
    for name, app_apks in apkeep_apks.items():
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


def install() -> None:
    data = config()
    packages = data["packages"]
    keymapper = packages["github"]["keymapper"]["package"]
    keymapper_was_installed = (
        f"package:{keymapper}"
        in shell("pm", "list", "packages", capture=True).splitlines()
    )
    install_apps(data)
    for package in packages["removed"]:
        log(f"remove {package}")
        subprocess.run(
            ["adb", "-s", TV, "shell", "pm", "uninstall", "--user", "0", package],
            check=False,
            stdout=subprocess.DEVNULL,
        )
    if not keymapper_was_installed:
        setup_automatic_backup(data)
        if MAPPINGS.exists():
            log("restore Key Mapper mappings")
            restore()
    log("apply TV settings, disable ADB, and reboot")
    finish(data)


def save_mappings() -> None:
    if subprocess.run(
        ["adb", "-s", TV, "shell", "test", "-e", REMOTE_BACKUP], check=False
    ).returncode:
        raise SystemExit(
            f"configure Key Mapper automatic backup at {REMOTE_BACKUP}, then retry"
        )
    FILES.mkdir(exist_ok=True)
    temporary = ROOT / ".download" / "key_mapper.zip"
    temporary.parent.mkdir(exist_ok=True)
    run("pull", REMOTE_BACKUP, str(temporary))
    with zipfile.ZipFile(temporary) as archive:
        mappings = json.loads(archive.read("data.json"))
    MAPPINGS.write_text(json.dumps(mappings, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        nargs="?",
        default="install",
        choices=("install", "update-apps", "save-mappings"),
    )
    args = parser.parse_args()
    subprocess.run(["adb", "connect", TV], check=True, stdout=subprocess.DEVNULL)
    run("wait-for-device")
    if args.command == "install":
        install()
    elif args.command == "update-apps":
        install_apps(config())
    else:
        save_mappings()


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as error:
        raise SystemExit(f"missing command or file: {error}")
