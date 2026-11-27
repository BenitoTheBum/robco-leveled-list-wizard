import shutil
"""Shared PyQt compatibility shims, constants, and JSON persistence for RobCo Wizard."""

import json
import os
from typing import Dict, Set

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QMessageBox
    _PYQT6 = True
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QMessageBox
    _PYQT6 = False

QtChecked   = Qt.CheckState.Checked    if hasattr(Qt, "CheckState")   else Qt.Checked
QtUnchecked = Qt.CheckState.Unchecked  if hasattr(Qt, "CheckState")   else Qt.Unchecked
QtUserRole  = Qt.ItemDataRole.UserRole if hasattr(Qt, "ItemDataRole") else Qt.UserRole
MsgYes      = QMessageBox.StandardButton.Yes if hasattr(QMessageBox, "StandardButton") else QMessageBox.Yes
MsgNo       = QMessageBox.StandardButton.No  if hasattr(QMessageBox, "StandardButton") else QMessageBox.No

OUTPUT_MOD_NAME = "RobCo Auto-Injected Patches"
PLUGIN_DIR      = os.path.dirname(__file__)
_APPDATA_CFG    = os.path.join(os.environ.get("LOCALAPPDATA", PLUGIN_DIR), "RobCoLeveledListWizard")
os.makedirs(_APPDATA_CFG, exist_ok=True)
for _fn in ("ignored_mods.json", "wizard_prefs.json", "batch_blacklist.json", "shield_whitelist.json"):
    _legacy = os.path.join(PLUGIN_DIR, _fn)
    _target = os.path.join(_APPDATA_CFG, _fn)
    if os.path.isfile(_legacy) and not os.path.isfile(_target):
        try:
            shutil.copy2(_legacy, _target)
        except Exception:
            pass
IGNORE_FILE     = os.path.join(_APPDATA_CFG, "ignored_mods.json")
PREFS_FILE      = os.path.join(_APPDATA_CFG, "wizard_prefs.json")
BLACKLIST_FILE  = os.path.join(_APPDATA_CFG, "batch_blacklist.json")
WHITELIST_FILE  = os.path.join(_APPDATA_CFG, "shield_whitelist.json")


def exec_dialog(dlg):
    return dlg.exec() if hasattr(dlg, "exec") else dlg.exec_()


def load_json_set(path: str, lower: bool = False) -> Set[str]:
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                vals = json.load(f)
                if isinstance(vals, list):
                    return {x.strip().lower() if lower else x.strip() for x in vals if isinstance(x, str) and x.strip()}
        except Exception:
            pass
    return set()


def save_json_set(path: str, items: Set[str]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(items), f, indent=2)
    except Exception:
        pass


def load_wizard_prefs() -> Dict[str, object]:
    if os.path.isfile(PREFS_FILE):
        try:
            with open(PREFS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {"include_script_injected": False}


def save_wizard_prefs(prefs: Dict[str, object]) -> None:
    try:
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except Exception:
        pass


def _overrides_path(mods_dir: str) -> str:
    return os.path.join(mods_dir, OUTPUT_MOD_NAME, "user_overrides.json")


def load_user_overrides(mods_dir: str) -> dict:
    path = _overrides_path(mods_dir)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_user_override(mods_dir: str, plugin_fname: str, entry: dict) -> None:
    if not plugin_fname:
        return
    data = load_user_overrides(mods_dir)
    data[plugin_fname.strip().lower()] = entry
    path = _overrides_path(mods_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def delete_user_override(mods_dir: str, plugin_fname: str) -> bool:
    data = load_user_overrides(mods_dir)
    key = plugin_fname.strip().lower()
    if key in data:
        del data[key]
        path = _overrides_path(mods_dir)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            pass
    return False


def load_blacklist() -> tuple:
    if os.path.isfile(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                plugins = {x.strip().lower() for x in data.get("plugins", []) if isinstance(x, str) and x.strip()}
                mods = {x.strip().lower() for x in data.get("mod_names", []) if isinstance(x, str) and x.strip()}
                return plugins, mods
        except Exception:
            pass
    return set(), set()


def save_blacklist(plugins: set, mod_names: set = None) -> None:
    if mod_names is None:
        _, mod_names = load_blacklist()
    try:
        with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"plugins": sorted(plugins), "mod_names": sorted(mod_names)}, f, indent=2)
    except Exception:
        pass


def auto_activate_output(organizer) -> None:
    """Refresh MO2 and auto-enable OUTPUT_MOD_NAME + generated ESPs in left and right panes."""
    try:
        organizer.refresh()
    except Exception:
        pass
    try:
        organizer.modList().setActive(OUTPUT_MOD_NAME, True)
    except Exception:
        pass
    try:
        import mobase
        plist = organizer.pluginList()
        for pn in ("RobCo_AutoSubLists.esp", "RobCo_OverrideShield.esp"):
            if pn in plist.pluginNames():
                plist.setState(pn, mobase.PluginState.ACTIVE)
    except Exception:
        pass
