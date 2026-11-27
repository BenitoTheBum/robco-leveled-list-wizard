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
IGNORE_FILE     = os.path.join(PLUGIN_DIR, "ignored_mods.json")
PREFS_FILE      = os.path.join(PLUGIN_DIR, "wizard_prefs.json")
BLACKLIST_FILE  = os.path.join(PLUGIN_DIR, "batch_blacklist.json")
WHITELIST_FILE  = os.path.join(PLUGIN_DIR, "shield_whitelist.json")


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
