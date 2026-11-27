"""Wizard UI pages for the RobCo Leveled List Wizard."""

import os

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QWizard, QWizardPage,
        QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QComboBox, QLineEdit,
        QTabWidget, QListWidget, QListWidgetItem,
        QCheckBox, QSpinBox, QMessageBox, QScrollArea, QWidget,
    )
    _PYQT6 = True
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (
        QWizard, QWizardPage,
        QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QComboBox, QLineEdit,
        QTabWidget, QListWidget, QListWidgetItem,
        QCheckBox, QSpinBox, QMessageBox, QScrollArea, QWidget,
    )
    _PYQT6 = False

from .robco_utils import (
    QtChecked, QtUnchecked, QtUserRole, MsgYes, MsgNo,
    OUTPUT_MOD_NAME, IGNORE_FILE, WHITELIST_FILE,
    exec_dialog as _exec_dialog, load_json_set, save_json_set,
)


def _set_modern_style(wizard):
    try:
        wizard.setWizardStyle(QWizard.WizardStyle.ModernStyle)
    except AttributeError:
        try:
            wizard.setWizardStyle(QWizard.ModernStyle)
        except AttributeError:
            pass


def _multiselect_mode():
    try:
        return QListWidget.SelectionMode.MultiSelection
    except AttributeError:
        return QListWidget.MultiSelection


import mobase  # noqa: E402
from .robco_parser import parse_plugin, find_already_patched_plugins
from .robco_engine import (
    WEAPON_LISTS, ARMOR_LISTS, CREATURE_LISTS,
    count_all_ll_entries,
    suggest_targets_heuristic,
    write_robco_ini,
)

class SelectItemsPage(QWizardPage):
    def __init__(self, wizard, parent=None, preselect_mod=None, preselect_plugin=None):
        super().__init__(parent)
        self._wizard = wizard
        self._preselect_mod = preselect_mod
        self._preselect_plugin = preselect_plugin
        self._all_candidate_mods = []
        self.setTitle("Select Mod and Items")
        self.setSubTitle("Choose which records to patch.")
        self._setup_ui()
        self.populate_mods()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        action_bar = QHBoxLayout()
        self.btn_next_mod = QPushButton("Next Unpatched Mod >>")
        self.btn_skip_mod = QPushButton("Skip / Ignore Mod")
        self.btn_batch    = QPushButton("Auto-Batch All Unpatched...")
        action_bar.addWidget(self.btn_next_mod)
        action_bar.addWidget(self.btn_skip_mod)
        action_bar.addWidget(self.btn_batch)
        layout.addLayout(action_bar)
        shield_bar = QHBoxLayout()
        self.btn_shield    = QPushButton("Build / Refresh Override Shield ESP")
        self.btn_whitelist = QPushButton("Whitelist Current Plugin (Allow Overrides)")
        self.chk_script_inj = QCheckBox("Include Script-Injected Mods (Injection Blocker)")
        self.chk_script_inj.setChecked(bool(self._wizard.settings.get("include_script_injected", False)))
        self.chk_script_inj.toggled.connect(self._on_toggle_script_inj)
        shield_bar.addWidget(self.btn_shield)
        shield_bar.addWidget(self.btn_whitelist)
        shield_bar.addWidget(self.chk_script_inj)
        layout.addLayout(shield_bar)


        grid = QGridLayout()
        grid.addWidget(QLabel("Search:"), 0, 0)
        self.search_mod = QLineEdit()
        self.search_mod.setPlaceholderText("Filter mods by name...")
        grid.addWidget(self.search_mod, 0, 1)

        grid.addWidget(QLabel("Mod:"), 1, 0)
        self.combo_mod = QComboBox()
        grid.addWidget(self.combo_mod, 1, 1)

        grid.addWidget(QLabel("Plugin:"), 2, 0)
        self.combo_plugin = QComboBox()
        grid.addWidget(self.combo_plugin, 2, 1)
        layout.addLayout(grid)

        self.lbl_warning = QLabel()
        self.lbl_warning.setStyleSheet("color: orange; font-weight: bold;")
        layout.addWidget(self.lbl_warning)

        self.tabs           = QTabWidget()
        self.list_weapons   = QListWidget()
        self.list_armors    = QListWidget()
        self.list_creatures = QListWidget()
        for lst in (self.list_weapons, self.list_armors, self.list_creatures):
            lst.setSelectionMode(_multiselect_mode())
        self.tabs.addTab(self.list_weapons,   "Weapons")
        self.tabs.addTab(self.list_armors,    "Armors / Outfits")
        self.tabs.addTab(self.list_creatures, "Creatures / NPCs")
        layout.addWidget(self.tabs)

        btn_row = QHBoxLayout()
        self.btn_check_all   = QPushButton("Check All in Tab")
        self.btn_uncheck_all = QPushButton("Uncheck All in Tab")
        btn_row.addWidget(self.btn_check_all)
        btn_row.addWidget(self.btn_uncheck_all)
        layout.addLayout(btn_row)

        self.search_mod.textChanged.connect(self._filter_mods)
        self.combo_mod.currentIndexChanged.connect(self._on_mod_changed)
        self.combo_plugin.currentIndexChanged.connect(self._parse_current_plugin)
        self.btn_next_mod.clicked.connect(self._on_next_unpatched)
        self.btn_skip_mod.clicked.connect(self._on_skip_ignore)
        self.btn_batch.clicked.connect(self._on_batch_preview)
        self.btn_check_all.clicked.connect(self._check_all_in_tab)
        self.btn_uncheck_all.clicked.connect(self._uncheck_all_in_tab)
        self.btn_shield.clicked.connect(self._on_build_shield)
        self.btn_whitelist.clicked.connect(self._on_toggle_whitelist)

    def populate_mods(self):
        self._all_candidate_mods = []
        mods_dir = self._wizard.organizer.modsPath()

        for mod_name in self._wizard.organizer.modList().allModsByProfilePriority():
            if mod_name == OUTPUT_MOD_NAME or mod_name in self._wizard.ignored_mods or mod_name.endswith("_separator"):
                continue
            if not bool(self._wizard.organizer.modList().state(mod_name) & mobase.ModState.ACTIVE):
                continue
            mod_path = os.path.join(mods_dir, mod_name)
            if not os.path.isdir(mod_path):
                continue
            has_plugin = any(f.lower().endswith((".esp", ".esl")) for f in os.listdir(mod_path))
            if has_plugin:
                self._all_candidate_mods.append(mod_name)

        self._filter_mods(self.search_mod.text(), initial_select=self._preselect_mod)

    def _filter_mods(self, text, initial_select=None):
        query = text.strip().lower() if isinstance(text, str) else ""
        target = initial_select or self.combo_mod.currentText()
        self.combo_mod.blockSignals(True)
        self.combo_mod.clear()
        for mod in self._all_candidate_mods:
            if not query or query in mod.lower():
                self.combo_mod.addItem(mod)
        if target and self.combo_mod.findText(target) >= 0:
            self.combo_mod.setCurrentText(target)
        elif self.combo_mod.count() > 0:
            self.combo_mod.setCurrentIndex(0)
        self.combo_mod.blockSignals(False)
        self._on_mod_changed()

    def _on_mod_changed(self):
        self.combo_plugin.blockSignals(True)
        self.combo_plugin.clear()
        mod_name = self.combo_mod.currentText()
        if mod_name:
            mod_path = os.path.join(self._wizard.organizer.modsPath(), mod_name)
            if os.path.isdir(mod_path):
                for entry in sorted(os.listdir(mod_path)):
                    if entry.lower().endswith((".esp", ".esl")):
                        self.combo_plugin.addItem(entry)
        if self._preselect_plugin and self.combo_plugin.findText(self._preselect_plugin) >= 0:
            self.combo_plugin.setCurrentText(self._preselect_plugin)
            self._preselect_plugin = None
        elif self.combo_plugin.count() > 0:
            self.combo_plugin.setCurrentIndex(0)
        self.combo_plugin.blockSignals(False)
        self._parse_current_plugin()

    def _parse_current_plugin(self):
        mod_name    = self.combo_mod.currentText()
        plugin_name = self.combo_plugin.currentText()
        self._clear_lists()
        self.lbl_warning.clear()
        if not mod_name or not plugin_name:
            self._wizard.current_parsed = None
            self._wizard.current_plugin = None
            return

        mods_dir = self._wizard.organizer.modsPath()
        resolved = self._wizard.organizer.resolvePath(plugin_name)
        target_path = resolved if resolved and os.path.isfile(resolved) else os.path.join(mods_dir, mod_name, plugin_name)
        parsed = parse_plugin(target_path)
        self._wizard.current_parsed = parsed
        self._wizard.current_plugin = plugin_name

        if not parsed:
            self.lbl_warning.setText("Failed to parse plugin")
            return
        from .robco_shield import is_protected_overhaul
        if is_protected_overhaul(plugin_name, parsed):
            self.lbl_warning.setText("Warning: Faction/NPC Overhaul detected (Auto-protected from Override Shield)")
        elif parsed.get("has_script_injector"):
            self.lbl_warning.setText("Warning: Mod contains a script injector quest")
        elif plugin_name.lower() in find_already_patched_plugins(mods_dir):
            self.lbl_warning.setText("Notice: This plugin is already patched")
        self._populate_lists(parsed)


    def _clear_lists(self):
        self.list_weapons.clear()
        self.list_armors.clear()
        self.list_creatures.clear()

    def _populate_lists(self, parsed: dict):
        self._clear_lists()
        root_weapons = [r for r in parsed.get("root_lvli", []) if r.get("category") == "WEAP"]
        self._fill_list(self.list_weapons, root_weapons, parsed.get("weap_families", []))

        root_armors = [r for r in parsed.get("root_lvli", []) if r.get("category") == "ARMO"]
        self._fill_list(self.list_armors, root_armors, parsed.get("armo_list", []))

        self._fill_list(self.list_creatures, parsed.get("npc_list", []), [])

    def _fill_list(self, lw: QListWidget, root_items: list, family_items: list):
        for rec in root_items:
            item = QListWidgetItem(rec.get("name", ""))
            item.setData(QtUserRole, rec)
            item.setCheckState(QtChecked)
            lw.addItem(item)
        for rec in family_items:
            item = QListWidgetItem(rec.get("name", ""))
            item.setData(QtUserRole, rec)
            check = QtChecked if (not root_items and not rec.get("is_unique", False)) else QtUnchecked
            item.setCheckState(check)
            lw.addItem(item)

    def _check_all_in_tab(self):
        lw = self.tabs.currentWidget()
        if isinstance(lw, QListWidget):
            for i in range(lw.count()):
                lw.item(i).setCheckState(QtChecked)

    def _uncheck_all_in_tab(self):
        lw = self.tabs.currentWidget()
        if isinstance(lw, QListWidget):
            for i in range(lw.count()):
                lw.item(i).setCheckState(QtUnchecked)

    def get_selected_items(self) -> dict:
        def collect(lw: QListWidget):
            return [
                lw.item(i).data(QtUserRole)
                for i in range(lw.count())
                if lw.item(i).checkState() == QtChecked
            ]
        return {
            "WEAP": collect(self.list_weapons),
            "ARMO": collect(self.list_armors),
            "NPC_": collect(self.list_creatures),
        }

    def _on_next_unpatched(self):
        self.search_mod.clear()
        mods_dir = self._wizard.organizer.modsPath()
        already_patched = find_already_patched_plugins(mods_dir)
        inc_script = bool(self._wizard.settings.get("include_script_injected", False))
        current = self.combo_mod.currentText()
        mod_names = list(self._wizard.organizer.modList().allModsByProfilePriority())
        try:
            start = mod_names.index(current) + 1
        except ValueError:
            start = 0

        for name in mod_names[start:]:
            if name == OUTPUT_MOD_NAME or name in self._wizard.ignored_mods or name.endswith("_separator"):
                continue
            if not bool(self._wizard.organizer.modList().state(name) & mobase.ModState.ACTIVE):
                continue
            mod_path = os.path.join(mods_dir, name)
            if not os.path.isdir(mod_path):
                continue
            has_unpatched = False
            for f in os.listdir(mod_path):
                if not f.lower().endswith((".esp", ".esl")) or f.lower() in already_patched:
                    continue
                if not inc_script:
                    res = self._wizard.organizer.resolvePath(f)
                    p_info = parse_plugin(res if res and os.path.isfile(res) else os.path.join(mod_path, f))
                    if p_info and p_info.get("has_script_injector"):
                        continue
                has_unpatched = True
                break
            if has_unpatched:
                idx = self.combo_mod.findText(name)
                if idx >= 0:
                    self.combo_mod.setCurrentIndex(idx)
                    return
        QMessageBox.information(self, "No More Mods", "No more unpatched active mods found.")

    def _on_skip_ignore(self):
        mod_name = self.combo_mod.currentText()
        if mod_name:
            self._wizard.ignored_mods.add(mod_name)
            save_json_set(IGNORE_FILE, self._wizard.ignored_mods)
        self._on_next_unpatched()

    def _on_batch_preview(self):
        from .batch_dialog import BatchPreviewDialog
        dlg = BatchPreviewDialog(
            self._wizard.organizer,
            parent=self,
            include_script_injected=self.chk_script_inj.isChecked(),
        )
        if _exec_dialog(dlg):
          self.populate_mods()

    def _on_toggle_script_inj(self, checked: bool):
        self._wizard.settings["include_script_injected"] = bool(checked)
        from . import load_wizard_prefs, save_wizard_prefs
        prefs = load_wizard_prefs()
        prefs["include_script_injected"] = bool(checked)
        save_wizard_prefs(prefs)

    def _on_toggle_whitelist(self):
        plugin = self.combo_plugin.currentText().strip()
        if not plugin:
            return
        wl = load_json_set(WHITELIST_FILE, lower=True)
        if plugin.lower() in wl:
            wl.remove(plugin.lower())
            msg = f"Removed {plugin} from Shield Whitelist (its vanilla LVLI/LVLN overrides WILL be blocked)."
        else:
            wl.add(plugin.lower())
            msg = f"Added {plugin} to Shield Whitelist (its vanilla LVLI/LVLN overrides will be ALLOWED)."
        save_json_set(WHITELIST_FILE, wl)
        QMessageBox.information(self, "Shield Whitelist Updated", msg)

    def _on_build_shield(self):
        from .robco_shield import build_override_shield
        mods_dir = self._wizard.organizer.modsPath()
        shield_path = os.path.join(mods_dir, OUTPUT_MOD_NAME, "RobCo_OverrideShield.esp")
        ok, count, sources = build_override_shield(self._wizard.organizer, shield_path, load_json_set(WHITELIST_FILE, lower=True))
        try:
            self._wizard.organizer.refresh()
        except Exception:
            pass
        if ok and count > 0:
            QMessageBox.information(
                self, "Override Shield Built",
                f"Built RobCo_OverrideShield.esp blocking {count} vanilla LVLI/LVLN overrides "
                f"from {len(sources)} converted plugin(s).\n\n"
                "Enable RobCo_OverrideShield.esp near the bottom of your load order!"
            )
        elif ok:
            QMessageBox.information(self, "Override Shield Clean", "No non-whitelisted vanilla LVLI/LVLN overrides found.")
        else:
            QMessageBox.warning(self, "Error", "Could not read Fallout4.esm to build Override Shield.")

    def nextId(self):
        return 1

class SelectTargetsPage(QWizardPage):
    def __init__(self, wizard, parent=None):
        super().__init__(parent)
        self._wizard = wizard
        self.setTitle("Select Vanilla Target Lists (Step 2 of 4)")
        self.setSubTitle("Choose which vanilla leveled lists to inject into.")
        self._checkboxes = {}
        self._cb_category = {}

        layout = QVBoxLayout(self)
        self._cols_layout = QHBoxLayout()
        layout.addLayout(self._cols_layout)


        self._lbl_summary = QLabel()
        layout.addWidget(self._lbl_summary)
        layout.addStretch()

    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def initializePage(self):
        self._clear_layout(self._cols_layout)
        self._checkboxes.clear()
        self._cb_category.clear()

        parsed = self._wizard.current_parsed or {}
        mods_dir = self._wizard.organizer.modsPath()
        counts = count_all_ll_entries(mods_dir)
        sug = suggest_targets_heuristic(parsed, counts)
        suggested_fids = set(sug.get("targets", []))

        sections = [
            ("WEAP", "WEAPONS", WEAPON_LISTS),
            ("ARMO", "ARMORS & WORLD LOOT", ARMOR_LISTS),
            ("NPC_", "CREATURE SPAWNS & INVENTORIES", CREATURE_LISTS),
        ]

        for cat_key, header_title, items_list in sections:
            col_box = QVBoxLayout()
            lbl_header = QLabel(f"=== {header_title} ===")
            lbl_header.setStyleSheet("color: #39ff14; font-weight: bold; padding-bottom: 4px;")
            col_box.addWidget(lbl_header)

            for label, fid in items_list:
                count = counts.get(fid.lower(), counts.get(fid, 0))
                cb = QCheckBox(f"{label}  [{count}/255]")
                cb.setChecked(fid in suggested_fids)
                if count >= 255:
                    cb.setStyleSheet("color: red; font-weight: bold;")
                elif count >= 200:
                    cb.setStyleSheet("color: orange;")
                self._checkboxes[fid] = cb
                self._cb_category[fid] = cat_key
                col_box.addWidget(cb)

            col_box.addStretch()
            self._cols_layout.addLayout(col_box)

    def get_selected_targets(self) -> dict:
        result = {"WEAP": [], "ARMO": [], "NPC_": []}
        for fid, cb in self._checkboxes.items():
            if cb.isChecked():
                cat = self._cb_category.get(fid, "WEAP")
                result[cat].append(fid)
        return result

class SelectOverhaulTargetsPage(QWizardPage):
    def __init__(self, wizard, parent=None):
        super().__init__(parent)
        self._wizard = wizard
        self.setTitle("Select Mod / Overhaul Target Lists (Step 3 of 4)")
        self.setSubTitle("Optional: Inject into custom leveled lists added by active overhaul mods (e.g., WATM).")
        self._checkboxes = {}
        self._cb_category = {}

        layout = QVBoxLayout(self)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter overhaul lists by plugin or EditorID...")
        self.search_box.textChanged.connect(self._filter_checkboxes)
        layout.addWidget(self.search_box)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._cols_layout = QHBoxLayout(self._container)
        self.scroll.setWidget(self._container)
        layout.addWidget(self.scroll)

    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def initializePage(self):
        from .robco_shield import is_protected_overhaul

        self._clear_layout(self._cols_layout)
        self._checkboxes.clear()
        self._cb_category.clear()
        self.search_box.clear()

        mods_dir = self._wizard.organizer.modsPath()
        counts = count_all_ll_entries(mods_dir)
        from .robco_shield import collect_overhaul_lists
        extra_weap, extra_armo = collect_overhaul_lists(self._wizard.organizer, self._wizard.current_plugin or "")

        if not extra_weap and not extra_armo:
            lbl = QLabel("No active overhaul mods with custom weapon/armor leveled lists were detected.")
            self._cols_layout.addWidget(lbl)
            return

        for cat_key, header_title, items_list in [
            ("WEAP", "OVERHAUL WEAPON LISTS", extra_weap),
            ("ARMO", "OVERHAUL ARMOR / OUTFIT LISTS", extra_armo),
        ]:
            col_box = QVBoxLayout()
            lbl_header = QLabel(f"=== {header_title} ===")
            lbl_header.setStyleSheet("color: #39ff14; font-weight: bold; padding-bottom: 4px;")
            col_box.addWidget(lbl_header)

            for label, fid in items_list:
                count = counts.get(fid.lower(), counts.get(fid, 0))
                cb = QCheckBox(f"{label}  [{count}/255]")
                if count >= 255:
                    cb.setStyleSheet("color: red; font-weight: bold;")
                elif count >= 200:
                    cb.setStyleSheet("color: orange;")
                self._checkboxes[fid] = cb
                self._cb_category[fid] = cat_key
                col_box.addWidget(cb)

            col_box.addStretch()
            self._cols_layout.addLayout(col_box)

    def _filter_checkboxes(self, text: str):
        q = text.strip().lower()
        for cb in self._checkboxes.values():
            cb.setVisible(not q or q in cb.text().lower())

    def get_selected_targets(self) -> dict:
        result = {"WEAP": [], "ARMO": [], "NPC_": []}
        for fid, cb in self._checkboxes.items():
            if not cb.isChecked():
                continue
            cat = self._cb_category.get(fid, "WEAP")
            result[cat].append(fid)
        return result

    def nextId(self):
        return 3
  
class TierSettingsPage(QWizardPage):
    def __init__(self, wizard, parent=None):
        super().__init__(parent)
        self._wizard = wizard
        self.setTitle("Tier & Spawn Weight Settings")
        self.setSubTitle("Check one or more tiers and set spawn Weight (copies injected into the draw pool).")

        layout = QVBoxLayout(self)
        grid = QGridLayout()

        self.chk_early  = QCheckBox("Early  (Min Level 1  | ChanceNone 0)")
        self.chk_mid    = QCheckBox("Mid    (Min Level 15 | ChanceNone 25)")
        self.chk_late   = QCheckBox("Late   (Min Level 30 | ChanceNone 50)")
        self.chk_custom = QCheckBox("Custom")

        self.w_early  = QSpinBox(); self.w_early.setRange(1, 10);  self.w_early.setValue(1);  self.w_early.setPrefix("Weight: ")
        self.w_mid    = QSpinBox(); self.w_mid.setRange(1, 10);    self.w_mid.setValue(1);    self.w_mid.setPrefix("Weight: ")
        self.w_late   = QSpinBox(); self.w_late.setRange(1, 10);   self.w_late.setValue(1);   self.w_late.setPrefix("Weight: ")
        self.w_custom = QSpinBox(); self.w_custom.setRange(1, 10); self.w_custom.setValue(1); self.w_custom.setPrefix("Weight: ")

        for row, (cb, sp) in enumerate([
            (self.chk_early, self.w_early),
            (self.chk_mid, self.w_mid),
            (self.chk_late, self.w_late),
            (self.chk_custom, self.w_custom),
        ]):
            grid.addWidget(cb, row, 0)
            grid.addWidget(sp, row, 1)

        layout.addLayout(grid)

        custom_row = QHBoxLayout()
        self.spin_level  = QSpinBox(); self.spin_level.setRange(1, 100);  self.spin_level.setValue(1)
        self.spin_chance = QSpinBox(); self.spin_chance.setRange(0, 99);  self.spin_chance.setValue(0)
        custom_row.addWidget(QLabel("Custom Min Level:"));  custom_row.addWidget(self.spin_level)
        custom_row.addWidget(QLabel("Custom ChanceNone:")); custom_row.addWidget(self.spin_chance)
        layout.addLayout(custom_row)

        self.checkbox_bundle = QCheckBox(
            "Bundle multi-item selections into 1-mod-1-vote sub-list (RobCo_AutoSubLists.esl)"
        )
        self.checkbox_bundle.setChecked(True)
        layout.addWidget(self.checkbox_bundle)

        self.checkbox_split_factions = QCheckBox(
            "Split multi-faction items by keyword (Gunner/BoS/Minutemen/Railroad/Institute)"
        )
        self.checkbox_split_factions.setChecked(True)
        layout.addWidget(self.checkbox_split_factions)
        layout.addStretch()

    def initializePage(self):
        parsed = self._wizard.current_parsed or {}
        lvlo_levels = parsed.get("lvlo_levels", [])
        for cb in (self.chk_early, self.chk_mid, self.chk_late, self.chk_custom):
            cb.setChecked(False)
        for sp in (self.w_early, self.w_mid, self.w_late, self.w_custom):
            sp.setValue(1)

        if lvlo_levels:
            detected_lvl = min(lvlo_levels)
            self.spin_level.setValue(max(1, min(100, detected_lvl)))
            self.chk_custom.setChecked(True)
            self.chk_custom.setText(f"Custom (Detected from mod LVLI: Level {detected_lvl})")
        else:
            self.chk_custom.setText("Custom")
            sug = suggest_targets_heuristic(parsed, {})
            tier = sug.get("tier", "early")
            if tier == "late":
                self.chk_late.setChecked(True)
            elif tier == "mid":
                self.chk_mid.setChecked(True)
            else:
                self.chk_early.setChecked(True)

    def get_selected_tiers(self) -> list:
        tiers = []
        if self.chk_early.isChecked():
            tiers.append((1, 0, self.w_early.value()))
        if self.chk_mid.isChecked():
            tiers.append((15, 25, self.w_mid.value()))
        if self.chk_late.isChecked():
            tiers.append((30, 50, self.w_late.value()))
        if self.chk_custom.isChecked():
            tiers.append((self.spin_level.value(), self.spin_chance.value(), self.w_custom.value()))
        return tiers or [(1, 0, 1)]

    def is_bundle(self) -> bool:
        return self.checkbox_bundle.isChecked()

    def is_split_factions(self) -> bool:
        return self.checkbox_split_factions.isChecked()

    def nextId(self):
        return -1


class RobCoFomodWizard(QWizard):
    def __init__(self, organizer, parent=None, settings=None, ignored_mods=None,
                 preselect_mod=None, plugin_name=None):
        super().__init__(parent)
        self.organizer    = organizer
        self.settings     = settings or {}
        self.ignored_mods = ignored_mods if ignored_mods is not None else set()

        self.current_parsed = None
        self.current_plugin = None

        self.setWindowTitle("RobCo Leveled List Wizard")
        self.resize(1100, 650)
        _set_modern_style(self)

        self.page_items    = SelectItemsPage(self, preselect_mod=preselect_mod, preselect_plugin=plugin_name)
        self.page_targets  = SelectTargetsPage(self)
        self.page_overhaul = SelectOverhaulTargetsPage(self)
        self.page_tier     = TierSettingsPage(self)

        self.addPage(self.page_items)
        self.addPage(self.page_targets)
        self.addPage(self.page_overhaul)
        self.addPage(self.page_tier)

    def accept(self):
        items      = self.page_items.get_selected_items()
        v_targets  = self.page_targets.get_selected_targets()
        ov_targets = self.page_overhaul.get_selected_targets()
        targets    = {
            cat: v_targets.get(cat, []) + ov_targets.get(cat, [])
            for cat in ("WEAP", "ARMO", "NPC_")
        }
        tiers   = self.page_tier.get_selected_tiers()
        bundle  = self.page_tier.is_bundle()

        plugin_fname = self.current_plugin or "unknown.esp"
        mod_name_txt = self.page_items.combo_mod.currentText() or "Unknown Mod"

        mods_dir = self.organizer.modsPath()
        ini_dir = os.path.join(
            mods_dir, OUTPUT_MOD_NAME,
            "F4SE", "Plugins", "RobCo_Patcher", "leveledList"
        )

        success = write_robco_ini(
            ini_dir, plugin_fname, mod_name_txt,
            items, targets,
            tiers, 0,
            bundle,
            split_factions=self.page_tier.is_split_factions(),
        )

        if success:
            try:
                self.organizer.refresh()
            except Exception:
                pass
            reply = QMessageBox.question(
                self, "Patch Saved",
                "Patch saved!\n\nJump to the next unpatched mod?",
                MsgYes | MsgNo,
            )
            if reply == MsgYes:
                self.restart()
                self.page_items._on_next_unpatched()
                return
        else:
            QMessageBox.warning(self, "Error", "Failed to write INI file. Check the log for details.")

        super().accept()
