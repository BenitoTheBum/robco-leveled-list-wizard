"""RobCo Leveled List Wizard — MO2 plugin entry point."""

import os
from typing import Dict, Set

import mobase

try:
    from PyQt6.QtWidgets import QMessageBox
    from PyQt6.QtGui import QIcon
except ImportError:
    from PyQt5.QtWidgets import QMessageBox
    from PyQt5.QtGui import QIcon

from .robco_parser import parse_plugin, find_already_patched_plugins
from .robco_shield import is_protected_overhaul
from .wizard_pages import RobCoFomodWizard

from .robco_utils import (
    OUTPUT_MOD_NAME, IGNORE_FILE,
    load_json_set, save_json_set, load_wizard_prefs, load_blacklist,
)

def load_ignored_mods() -> Set[str]:
    return load_json_set(IGNORE_FILE)

def save_ignored_mods(mod_set: Set[str]) -> None:
    save_json_set(IGNORE_FILE, mod_set)


class RobCoWizardPlugin(mobase.IPluginTool):
    def __init__(self):
        super().__init__()
        self.organizer = None
        self.parent_widget = None
        self._ignored_mods: Set[str] = load_ignored_mods()
        self._wizard = None

    def init(self, organizer) -> bool:
        self.organizer = organizer
        organizer.modList().onModInstalled(self._on_mod_installed)
        return True

    def name(self) -> str:
        return "RobCo Wizard"

    def displayName(self) -> str:
        return "RobCo Leveled List Wizard"

    def description(self) -> str:
        return "Auto-generates leveled list patches for Fallout 4 mods"

    def author(self) -> str:
        return "RobCo"

    def version(self) -> str:
        return "0.2.0-alpha"

    def isActive(self) -> bool:
        return True

    def tooltip(self) -> str:
        return "Creates leveled list patches for mods"

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        return QIcon(icon_path) if os.path.isfile(icon_path) else QIcon()

    def setParentWidget(self, widget) -> None:
        self.parent_widget = widget

    def display(self) -> bool:
        preselect_mod = None
        try:
            selected = self.organizer.modList().selectedMods()
            if selected:
                preselect_mod = str(selected[0]) if isinstance(selected, (list, tuple)) else str(selected)
        except Exception:
            pass
        self._launch_wizard(preselect_mod=preselect_mod)
        return True

    def settings(self):
        return [
            mobase.PluginSetting(
                "auto_launch_on_install",
                "Automatically launch wizard when installing a mod with unpatched leveled lists",
                True,
            ),
        ]

    def _current_settings(self) -> Dict[str, object]:
        prefs = load_wizard_prefs()
        if not self.organizer:
            return prefs
        prefs.update({
            "auto_launch_on_install": self.organizer.pluginSetting(self.name(), "auto_launch_on_install"),
        })
        return prefs

    def _on_mod_installed(self, mod) -> None:
        if not self.organizer:
            return
        mod_name = mod.name() if hasattr(mod, "name") else str(mod)
        if mod_name == OUTPUT_MOD_NAME or mod_name in self._ignored_mods:
            return
        if not self.organizer.pluginSetting(self.name(), "auto_launch_on_install"):
            return

        inc_script = bool(load_wizard_prefs().get("include_script_injected", False))
        mods_dir = self.organizer.modsPath()
        mod_path = os.path.join(mods_dir, mod_name)
        if not os.path.isdir(mod_path):
            return

        already_patched = find_already_patched_plugins(mods_dir)
        _bl_p, _ = load_blacklist()
        already_patched |= _bl_p
        for fname in os.listdir(mod_path):
            if not fname.lower().endswith((".esp", ".esl")) or fname.lower() in already_patched:
                continue
            parsed = parse_plugin(os.path.join(mod_path, fname))
            if not parsed or (parsed.get("has_script_injector") and not inc_script) or is_protected_overhaul(fname, parsed):
                continue
            if any(parsed.get(k) for k in ("root_lvli", "weap_families", "armo_list", "npc_list")):
                self._launch_wizard(preselect_mod=mod_name, plugin_name=fname)
                return

    def _launch_wizard(self, preselect_mod=None, plugin_name=None) -> None:
        self._wizard = RobCoFomodWizard(
            organizer=self.organizer,
            parent=None,
            settings=self._current_settings(),
            ignored_mods=self._ignored_mods,
            preselect_mod=preselect_mod,
            plugin_name=plugin_name,
        )
        self._wizard.show()


def createPlugin():
    return RobCoWizardPlugin()
