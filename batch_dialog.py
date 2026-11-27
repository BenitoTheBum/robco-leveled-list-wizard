"""Batch preview dialog for the RobCo Leveled List Wizard.

Shows a table of all unpatched active mods with heuristic suggestions,
lets the user quick-edit vanilla + overhaul targets and tiers on any row,
and generates multiple INI patches in one go.
"""

import csv
import json
import os

import mobase

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QAbstractItemView, QCheckBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QMenu,
        QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
        QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    )
    _PYQT6 = True
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (
        QAbstractItemView, QCheckBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QMenu,
        QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
        QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    )
    _PYQT6 = False

# ---------------------------------------------------------------------------
# Compat shims
# ---------------------------------------------------------------------------
def _stretch_mode():
    try:
        return QHeaderView.ResizeMode.Stretch
    except AttributeError:
        return QHeaderView.Stretch


from .robco_utils import (
    QtChecked, QtUnchecked, QtUserRole,
    OUTPUT_MOD_NAME, IGNORE_FILE,
    exec_dialog as _exec_dialog, load_json_set, save_json_set,
    load_blacklist as _load_blacklist, save_blacklist as _save_blacklist, load_user_overrides,
)


# ---------------------------------------------------------------------------
# Sibling imports
# ---------------------------------------------------------------------------
from .robco_parser import find_already_patched_plugins, parse_plugin
from .robco_engine import (
    ARMOR_LISTS, CREATURE_LISTS, WEAPON_LISTS,
    count_all_ll_entries, suggest_targets_heuristic, write_robco_ini,
)
from .robco_shield import is_protected_overhaul


_WEAP_FIDS = {fid for _, fid in WEAPON_LISTS}
_ARMO_FIDS = {fid for _, fid in ARMOR_LISTS}
_NPC_FIDS  = {fid for _, fid in CREATURE_LISTS}
_FID_TO_LABEL = {fid: lbl for lbl, fid in WEAPON_LISTS + ARMOR_LISTS + CREATURE_LISTS}

_CREATURE_KEYWORDS = (
    "mutant", "ghoul", "deathclaw", "mirelurk", "radscorpion",
    "yaoguai", "yao guai", "radstag", "creature", "monster", "beast", "animal",
)


def _read_mo2_categories(mod_dir: str) -> set:
    meta_path = os.path.join(mod_dir, "meta.ini")
    if not os.path.isfile(meta_path):
        return set()
    try:
        with open(meta_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip().lower().startswith("category="):
                    raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return {c.strip() for c in raw.split(",") if c.strip() and c.strip() != "0"}
    except Exception:
        pass
    return set()


def _load_ignored() -> set:
    return load_json_set(IGNORE_FILE)

def _save_ignored(mods: set):
    save_json_set(IGNORE_FILE, mods)


# ---------------------------------------------------------------------------
class QuickEditRowDialog(QDialog):
    """Two-tab popup editor for Vanilla + Overhaul target lists and tier/weight settings."""

    def __init__(self, mod_name: str, fname: str, sug: dict, counts: dict,
                 extra_weap: list, extra_armo: list, label_map: dict,
                 parsed: dict = None, mods_dir: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Quick Edit — {mod_name} ({fname})")
        self.resize(1100, 650)
        self._checkboxes = {}
        self._cb_category = {}
        self._ov_checkboxes = {}
        self._label_map = label_map
        self._parsed = parsed or {}
        self._mods_dir = mods_dir

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        selected = set(sug.get("targets", []))

        # --- Tab 1: Vanilla Target Lists ---
        tab_vanilla = QWidget()
        v_lay = QVBoxLayout(tab_vanilla)
        v_scroll = QScrollArea()
        v_scroll.setWidgetResizable(True)
        v_container = QWidget()
        v_cols = QHBoxLayout(v_container)

        sections = [
            ("WEAP", "WEAPONS", WEAPON_LISTS),
            ("ARMO", "ARMORS & WORLD LOOT", ARMOR_LISTS),
            ("NPC_", "CREATURE SPAWNS & INVENTORIES", CREATURE_LISTS),
        ]
        for cat_key, header_title, items_list in sections:
            col_box = QVBoxLayout()
            lbl = QLabel(f"=== {header_title} ===")
            lbl.setStyleSheet("color: #39ff14; font-weight: bold;")
            col_box.addWidget(lbl)
            for label, fid in items_list:
                cnt = counts.get(fid.lower(), counts.get(fid, 0))
                cb = QCheckBox(f"{label} [{cnt}/255]")
                cb.setChecked(fid in selected)
                self._checkboxes[fid] = cb
                self._cb_category[fid] = cat_key
                col_box.addWidget(cb)
            col_box.addStretch()
            v_cols.addLayout(col_box)

        v_scroll.setWidget(v_container)
        v_lay.addWidget(v_scroll)
        tabs.addTab(tab_vanilla, "1. Vanilla Target Lists")

        # --- Tab 2: Mod / Overhaul Target Lists ---
        tab_overhaul = QWidget()
        ov_lay = QVBoxLayout(tab_overhaul)
        self.ov_search = QLineEdit()
        self.ov_search.setPlaceholderText("Filter overhaul lists by plugin or EditorID...")
        self.ov_search.textChanged.connect(self._filter_overhaul)
        ov_lay.addWidget(self.ov_search)

        ov_scroll = QScrollArea()
        ov_scroll.setWidgetResizable(True)
        ov_container = QWidget()
        ov_cols = QHBoxLayout(ov_container)

        if not extra_weap and not extra_armo:
            ov_cols.addWidget(QLabel("No active overhaul mods with custom weapon/armor leveled lists detected."))
        else:
            for cat_key, header_title, items_list in [
                ("WEAP", "OVERHAUL WEAPON LISTS", extra_weap),
                ("ARMO", "OVERHAUL ARMOR / OUTFIT LISTS", extra_armo),
            ]:
                col_box = QVBoxLayout()
                lbl = QLabel(f"=== {header_title} ===")
                lbl.setStyleSheet("color: #39ff14; font-weight: bold;")
                col_box.addWidget(lbl)
                for label, fid in items_list:
                    cnt = counts.get(fid.lower(), counts.get(fid, 0))
                    cb = QCheckBox(f"{label} [{cnt}/255]")
                    cb.setChecked(fid in selected)
                    self._checkboxes[fid] = cb
                    self._cb_category[fid] = cat_key
                    self._ov_checkboxes[fid] = cb
                    col_box.addWidget(cb)
                col_box.addStretch()
                ov_cols.addLayout(col_box)

        ov_scroll.setWidget(ov_container)
        ov_lay.addWidget(ov_scroll)
        tabs.addTab(tab_overhaul, f"2. Mod / Overhaul Target Lists ({len(extra_weap) + len(extra_armo)})")

        # --- Tier & Weight Controls ---
        tier_grid = QGridLayout()
        self.spin_level = QSpinBox()
        self.spin_level.setRange(1, 100)
        self.spin_level.setValue(int(sug.get("level", 1)))

        self.spin_chance = QSpinBox()
        self.spin_chance.setRange(0, 99)
        self.spin_chance.setValue(int(sug.get("chance", 0)))

        self.spin_weight = QSpinBox()
        self.spin_weight.setRange(1, 10)
        self.spin_weight.setValue(int(sug.get("weight", 1)))

        tier_grid.addWidget(QLabel("Min Level:"), 0, 0)
        tier_grid.addWidget(self.spin_level, 0, 1)
        tier_grid.addWidget(QLabel("ChanceNone:"), 0, 2)
        tier_grid.addWidget(self.spin_chance, 0, 3)
        tier_grid.addWidget(QLabel("Spawn Weight:"), 0, 4)
        tier_grid.addWidget(self.spin_weight, 0, 5)
        layout.addLayout(tier_grid)

        btns = QHBoxLayout()
        btn_ok = QPushButton("Apply to Row")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

    def _filter_overhaul(self, text: str):
        q = text.strip().lower()
        for cb in self._ov_checkboxes.values():
            cb.setVisible(not q or q in cb.text().lower())

    def get_updated_sug(self, old_sug: dict) -> dict:
        new_targets = []
        target_cats = {}
        for fid, cb in self._checkboxes.items():
            if cb.isChecked():
                new_targets.append(fid)
                target_cats[fid] = self._cb_category.get(fid, "WEAP")
        lvl = self.spin_level.value()
        tier_name = "early" if lvl < 15 else ("mid" if lvl < 30 else "late")
        updated = dict(old_sug)
        updated["targets"] = new_targets
        updated["target_cats"] = target_cats
        updated["level"] = lvl
        updated["chance"] = self.spin_chance.value()
        updated["weight"] = self.spin_weight.value()
        updated["tier"] = tier_name
        return updated


# ---------------------------------------------------------------------------
class BatchPreviewDialog(QDialog):
    """Preview and batch-apply RobCo Patcher INI generation for multiple mods."""

    def __init__(self, organizer, parent=None, include_script_injected: bool = False):
        super().__init__(parent)
        self.organizer = organizer
        self._skipped_mods = []
        self._counts = {}
        self._extra_weap = []
        self._extra_armo = []
        self._label_map = dict(_FID_TO_LABEL)
        self.setWindowTitle("Auto-Batch Preview — Unpatched Active Mods (Double-click a row to edit)")
        self.resize(1220, 650)

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter batch list by mod name, plugin, or target faction...")
        self.search_box.textChanged.connect(self._filter_table)
        top_row.addWidget(self.search_box)


        self.chk_script_inj = QCheckBox("Include Script-Injected Mods")
        self.chk_script_inj.setChecked(bool(include_script_injected))
        self.chk_script_inj.toggled.connect(self._on_toggle_script_inj)
        top_row.addWidget(self.chk_script_inj)
        layout.addLayout(top_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Apply", "Mod Name", "Plugin", "Items to Inject", "Suggested Targets", "Tier / Weight"]
        )
        self.table.setWordWrap(True)
        try:
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        except AttributeError:
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.cellDoubleClicked.connect(self._on_edit_row)
        try:
            self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        except AttributeError:
            self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, _stretch_mode())
        header.setSectionResizeMode(3, _stretch_mode())
        header.setSectionResizeMode(4, _stretch_mode())
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()

        btn_sel_menu = QPushButton("Selection & Blacklist")
        menu_sel = QMenu(btn_sel_menu)
        menu_sel.addAction("Check All", lambda: self._set_all_checks(QtChecked))
        menu_sel.addAction("Uncheck All", lambda: self._set_all_checks(QtUnchecked))
        menu_sel.addSeparator()
        menu_sel.addAction("Blacklist Selected", self._blacklist_selected_rows)
        menu_sel.addAction("Manage Blacklist...", self._manage_blacklist_dialog)
        btn_sel_menu.setMenu(menu_sel)


        btn_tools_menu = QPushButton("Tools")
        menu_tools = QMenu(btn_tools_menu)
        menu_tools.addAction("Export Preview CSV", self._export_preview_csv)
        menu_tools.addAction("Purge Wizard Output...", self._purge_wizard_output)
        btn_tools_menu.setMenu(menu_tools)

        btn_edit_row = QPushButton("Edit Selected Row...")
        btn_apply    = QPushButton("Generate Selected INIs")
        btn_cancel   = QPushButton("Cancel")

        btn_edit_row.clicked.connect(self._on_edit_selected_btn)
        btn_apply.clicked.connect(self._apply_batch)
        btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(btn_sel_menu)
        btn_row.addWidget(btn_tools_menu)
        btn_row.addStretch()
        btn_row.addWidget(btn_edit_row)
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self._scan_mods()
    def _on_toggle_script_inj(self, checked: bool):
        try:
            from . import save_wizard_prefs
            save_wizard_prefs({"include_script_injected": bool(checked)})
        except Exception:
            pass
        self.table.setRowCount(0)
        self._scan_mods()
        self._filter_table(self.search_box.text())

    def _set_all_checks(self, state):
        checked = (state == QtChecked)
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            cb = self._get_row_checkbox(row)
            if cb:
                cb.setChecked(checked)

    def _filter_table(self, text: str):
        q = text.strip().lower()
        for row in range(self.table.rowCount()):
            if not q:
                self.table.setRowHidden(row, False)
                continue
            row_text = " ".join(
                (self.table.item(row, col).text() if self.table.item(row, col) else "")
                for col in (1, 2, 3, 4)
            ).lower()
            self.table.setRowHidden(row, q not in row_text)

    def _get_row_checkbox(self, row: int):
        cell_w = self.table.cellWidget(row, 0)
        return cell_w.findChild(QCheckBox) if cell_w else None

    def _on_edit_selected_btn(self):
        row = self.table.currentRow()
        if row >= 0:
            self._on_edit_row(row, 0)

    def _on_edit_row(self, row: int, _col: int):
        chk = self.table.item(row, 0)
        if not chk:
            return
        mod_name, fname, parsed, sug = chk.data(QtUserRole)
        dlg = QuickEditRowDialog(
            mod_name, fname, sug, self._counts,
            self._extra_weap, self._extra_armo, self._label_map,
            parsed=parsed, mods_dir=self.organizer.modsPath(), parent=self,
        )
        if _exec_dialog(dlg):
            new_sug = dlg.get_updated_sug(sug)
            from .robco_utils import save_user_override
            save_user_override(self.organizer.modsPath(), fname, {
                "targets": new_sug.get("targets", []),
                "target_cats": new_sug.get("target_cats", {}),
                "level": new_sug.get("level", 1),
                "chance": new_sug.get("chance", 0),
                "weight": new_sug.get("weight", 1),
            })
            chk.setData(QtUserRole, (mod_name, fname, parsed, new_sug))
            cb = self._get_row_checkbox(row)
            if cb:
                cb.setChecked(bool(new_sug["targets"]))
            self._refresh_row_display(row, new_sug)
            self.table.resizeRowsToContents()

    # ------------------------------------------------------------------
    def _get_injectable_records(self, parsed: dict) -> dict:
        _UNIQUE_MARKERS = ("unique", "legendary", "quest", "boss", "'s ")

        def _non_unique(r: dict) -> bool:
            if r.get("is_unique"):
                return False
            txt = f"{r.get('name', '')} {r.get('edid', '')}".lower()
            return not any(m in txt for m in _UNIQUE_MARKERS)

        root_weap = [x for x in parsed.get("root_lvli", []) if x.get("category") == "WEAP"]
        root_armo = [x for x in parsed.get("root_lvli", []) if x.get("category") == "ARMO"]
        # If mod defines explicit root LVLIs for one gear type only, ignore stray preview/dummy records of the other type
        if root_armo and not root_weap:
            weap_sel = []
            armo_sel = root_armo
        elif root_weap and not root_armo:
            weap_sel = root_weap
            armo_sel = []
        else:
            weap_sel = root_weap or [w for w in parsed.get("weap_families", []) if _non_unique(w)]
            armo_sel = root_armo or [a for a in parsed.get("armo_list", []) if _non_unique(a)]
        npc_sel = [] if (weap_sel or armo_sel) else [
            n for n in parsed.get("npc_list", [])
            if _non_unique(n) and not any(bad in f"{n.get('name', '')} {n.get('edid', '')}".lower() for bad in ("audiotemplate", "%%error"))
        ]
        return {
            "WEAP": weap_sel,
            "ARMO": armo_sel,
            "NPC_": npc_sel,
        }

    def _format_items_summary(self, selections: dict):
        flat = []
        for cat in ("WEAP", "ARMO", "NPC_"):
            for rec in selections.get(cat, []):
                nm = rec.get("name") or rec.get("edid") or rec.get("form_id", "?")
                fid = rec.get("form_id", "")
                flat.append((cat, nm, fid))
        if not flat:
            return "(None)", "No injectable records found"
        preview = ", ".join(nm for _, nm, _ in flat[:4])
        if len(flat) > 4:
            preview += f" (+{len(flat) - 4} more)"
        summary = f"[{len(flat)}] {preview}"
        tooltip = "\n".join(f"• [{cat}] {nm} ({fid})" for cat, nm, fid in flat)
        return summary, tooltip

    def _on_table_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        if not self.table.selectionModel().isRowSelected(idx.row(), idx.parent()):
            self.table.selectRow(idx.row())
        menu = QMenu(self)
        act_edit   = menu.addAction("Edit Selected Row...")
        act_rst_ov = menu.addAction("Reset Saved Override to Heuristic Default")
        act_bl_esp = menu.addAction("Blacklist Plugin(s) (ESP/ESL Only)")
        act_ign_md = menu.addAction("Ignore Entire Mod(s) (Syncs with Page 1)")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos)) if hasattr(menu, "exec") else menu.exec_(self.table.viewport().mapToGlobal(pos))
        if chosen == act_edit:
            self._on_edit_row(idx.row(), 0)
        elif chosen == act_rst_ov:
            chk = self.table.item(idx.row(), 0)
            if chk:
                _, fn, parsed, _ = chk.data(QtUserRole)
                from .robco_utils import delete_user_override
                delete_user_override(self.organizer.modsPath(), fn)
                fresh = suggest_targets_heuristic(parsed, self._counts)
                fresh.setdefault("weight", 1)
                chk.setData(QtUserRole, (chk.data(QtUserRole)[0], fn, parsed, fresh))
                self._refresh_row_display(idx.row(), fresh)
        elif chosen == act_bl_esp:
            self._blacklist_selected_rows(entire_mod=False)
        elif chosen == act_ign_md:
            self._blacklist_selected_rows(entire_mod=True)

    def _blacklist_selected_rows(self, entire_mod: bool = False):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "Blacklist Selected", "Select one or more rows in the table first.")
            return
        bl_plugins, bl_mods = _load_blacklist()
        user_ovs = load_user_overrides(mods_dir)
        ignored = _load_ignored()
        added = []
        target_mods = set()
        for r in rows:
            chk = self.table.item(r, 0)
            if chk:
                mod_name, fname, _, _ = chk.data(QtUserRole)
                if entire_mod:
                    ignored.add(mod_name)
                    target_mods.add(mod_name)
                    added.append(mod_name)
                else:
                    bl_plugins.add(fname.lower())
                    added.append(f"{mod_name} ({fname})")
            self.table.removeRow(r)

        if entire_mod:
            for r in range(self.table.rowCount() - 1, -1, -1):
                chk = self.table.item(r, 0)
                if chk and chk.data(QtUserRole) in target_mods:
                    self.table.removeRow(r)
            _save_ignored(ignored)
            QMessageBox.information(
                self,
                "Ignored Mods (Synced)",
                f"Added {len(target_mods)} mod(s) to ignored_mods.json (skipped on both Page 1 and Batch):\n"
                + "\n".join(f"? {m}" for m in sorted(target_mods)),
            )
        else:
            _save_blacklist(bl_plugins, bl_mods)
            QMessageBox.information(
                self,
                "Blacklisted Plugins",
                f"Added {len(added)} plugin(s) to batch_blacklist.json:\n"
                + "\n".join(f"? {x}" for x in added),
            )

    def _manage_blacklist_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Manage Blacklisted Plugins & Ignored Mods")
        dlg.resize(580, 450)
        lay = QVBoxLayout(dlg)

        tabs = QTabWidget()
        lay.addWidget(tabs)

        tab_esp = QWidget()
        esp_lay = QVBoxLayout(tab_esp)
        esp_lay.addWidget(QLabel("Individual plugins (.esp / .esl) skipped in Auto-Batch and Page 1 stepper:"))
        lw_esp = QListWidget()
        try:
            lw_esp.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        except AttributeError:
            lw_esp.setSelectionMode(QAbstractItemView.ExtendedSelection)
        bl_plugins, _ = _load_blacklist()
        for pn in sorted(bl_plugins):
            lw_esp.addItem(pn)
        esp_lay.addWidget(lw_esp)
        btn_rem_esp = QPushButton("Restore Selected Plugin(s)")
        esp_lay.addWidget(btn_rem_esp)
        tabs.addTab(tab_esp, f"1. Blacklisted Plugins ({lw_esp.count()})")

        tab_mod = QWidget()
        mod_lay = QVBoxLayout(tab_mod)
        mod_lay.addWidget(QLabel("Full MO2 mods ignored across BOTH Page 1 ('Skip / Ignore Mod') and Auto-Batch:"))
        lw_mod = QListWidget()
        try:
            lw_mod.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        except AttributeError:
            lw_mod.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for mn in sorted(_load_ignored()):
            lw_mod.addItem(mn)
        mod_lay.addWidget(lw_mod)
        btn_rem_mod = QPushButton("Restore Selected Mod(s)")
        mod_lay.addWidget(btn_rem_mod)
        tabs.addTab(tab_mod, f"2. Ignored Mods ({lw_mod.count()})")

        tab_ov = QWidget()
        ov_lay = QVBoxLayout(tab_ov)
        ov_lay.addWidget(QLabel("Saved custom rules in user_overrides.json (persists across purges):"))
        lw_ov = QListWidget()
        try:
            lw_ov.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        except AttributeError:
            lw_ov.setSelectionMode(QAbstractItemView.ExtendedSelection)
        from .robco_utils import load_user_overrides, delete_user_override
        for pn in sorted(load_user_overrides(self.organizer.modsPath()).keys()):
            lw_ov.addItem(pn)
        ov_lay.addWidget(lw_ov)
        btn_rem_ov = QPushButton("Delete Selected Saved Override(s)")
        ov_lay.addWidget(btn_rem_ov)
        tabs.addTab(tab_ov, f"3. Saved Overrides ({lw_ov.count()})")

        def _restore_ovs():
            items = lw_ov.selectedItems()
            if not items:
                return
            for it in items:
                delete_user_override(self.organizer.modsPath(), it.text().strip())
                lw_ov.takeItem(lw_ov.row(it))
            tabs.setTabText(2, f"3. Saved Overrides ({lw_ov.count()})")
            changed[0] = True

        btn_rem_ov.clicked.connect(_restore_ovs)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Close")
        close_row.addWidget(btn_close)
        lay.addLayout(close_row)

        changed = [False]

        def _restore_esps():
            items = lw_esp.selectedItems()
            if not items:
                return
            cur_p, cur_m = _load_blacklist()
            for it in items:
                cur_p.discard(it.text().strip().lower())
                lw_esp.takeItem(lw_esp.row(it))
            _save_blacklist(cur_p, cur_m)
            tabs.setTabText(0, f"1. Blacklisted Plugins ({lw_esp.count()})")
            changed[0] = True

        def _restore_mods():
            items = lw_mod.selectedItems()
            if not items:
                return
            cur_ign = _load_ignored()
            for it in items:
                cur_ign.discard(it.text().strip())
                lw_mod.takeItem(lw_mod.row(it))
            _save_ignored(cur_ign)
            tabs.setTabText(1, f"2. Ignored Mods ({lw_mod.count()})")
            changed[0] = True

        btn_rem_esp.clicked.connect(_restore_esps)
        btn_rem_mod.clicked.connect(_restore_mods)
        btn_close.clicked.connect(dlg.accept)
        _exec_dialog(dlg)

        if changed[0]:
            self.table.setRowCount(0)
            self._scan_mods()
            self._filter_table(self.search_box.text())

    def _purge_wizard_output(self):
        out_root = os.path.join(self.organizer.modsPath(), OUTPUT_MOD_NAME)
        ini_dir = os.path.join(out_root, "F4SE", "Plugins", "RobCo_Patcher", "leveledList")
        yes_btn = QMessageBox.StandardButton.Yes if hasattr(QMessageBox, "StandardButton") else QMessageBox.Yes
        no_btn  = QMessageBox.StandardButton.No  if hasattr(QMessageBox, "StandardButton") else QMessageBox.No
        reply = QMessageBox.question(
            self,
            "Purge Wizard Output",
            "Delete all wizard-generated *_RobCo_LL.ini / *_RobCo_OMOD.ini files and reset RobCo_AutoSubLists.esl so you can re-generate fresh patches?\n\n"
            "(Custom INIs not ending in _RobCo_LL.ini and RobCo_OverrideShield.esp will be kept.)",
            yes_btn | no_btn,
        )
        if reply != yes_btn:
            return

        removed_inis = 0
        if os.path.isdir(ini_dir):
            for fn in os.listdir(ini_dir):
                if fn.lower().endswith(("_robco_ll.ini", "_robco_omod.ini")):
                    try:
                        os.remove(os.path.join(ini_dir, fn))
                        removed_inis += 1
                    except Exception:
                        pass

        esl_path = os.path.join(out_root, "RobCo_AutoSubLists.esl")
        if os.path.isfile(esl_path):
            try:
                os.remove(esl_path)
            except Exception:
                pass

        try:
            self.organizer.refresh()
        except Exception:
            pass

        self.table.setRowCount(0)
        self._scan_mods()
        self._filter_table(self.search_box.text())
        QMessageBox.information(
            self,
            "Purge Complete",
            f"Removed {removed_inis} wizard INI file(s) and reset RobCo_AutoSubLists.esl.\n"
            f"Rescanned {self.table.rowCount()} unpatched mod(s).",
        )

    def _export_preview_csv(self):
        out_dir = os.path.join(self.organizer.modsPath(), OUTPUT_MOD_NAME)
        os.makedirs(out_dir, exist_ok=True)
        csv_path = os.path.join(out_dir, "RobCo_Batch_Preview.csv")
        rows = []
        for row in range(self.table.rowCount()):
            chk = self.table.item(row, 0)
            cb = self._get_row_checkbox(row)
            mod_name, fname, parsed, sug = chk.data(QtUserRole)
            sels = self._get_injectable_records(parsed)
            item_names = "; ".join(
                f"[{c}] {r.get('name') or r.get('edid') or r.get('form_id')}"
                for c in ("WEAP", "ARMO", "NPC_") for r in sels.get(c, [])
            )
            target_names = " | ".join(self._label_map.get(t, t) for t in sug.get("targets", []))
            rows.append([
                "YES" if (cb and cb.isChecked()) else "NO",
                mod_name, fname, item_names, target_names,
                sug.get("level", 1), sug.get("chance", 0), sug.get("weight", 1),
            ])
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Checked", "Mod_Name", "Plugin", "Items_To_Inject", "Target_Lists", "Min_Level", "ChanceNone", "Weight"])
            w.writerows(rows)
        try:
            os.startfile(csv_path)
        except Exception:
            QMessageBox.information(self, "Preview Exported", f"Saved preview CSV to:\n{csv_path}")

    def _refresh_row_display(self, row: int, sug: dict):
        chk = self.table.item(row, 0)
        if chk:
            _, _, parsed, _ = chk.data(QtUserRole)
            if sug.get("omod_map") or sug.get("obts_targets"):
                omods = parsed.get("omod_list", [])
                preview = ", ".join(o.get("name") or o.get("edid") or o.get("form_id", "?") for o in omods[:4])
                if len(omods) > 4:
                    preview += f" (+{len(omods) - 4} more)"
                items_cell = QTableWidgetItem(f"[{len(omods)} OMODs] {preview}")
                items_cell.setToolTip("\n".join(f"? [OMOD] {o.get('name')} ({o.get('form_id')})" for o in omods))
                self.table.setItem(row, 3, items_cell)
            else:
                sels = self._get_injectable_records(parsed)
                summary, item_tip = self._format_items_summary(sels)
                items_cell = QTableWidgetItem(summary)
                items_cell.setToolTip(item_tip)
                self.table.setItem(row, 3, items_cell)

        target_names = [self._label_map.get(t, t) for t in sug["targets"]]
        labels = ", ".join(target_names) if target_names else "(None selected)"
        tooltip_text = "\n".join(f"• {lbl}" for lbl in target_names) if target_names else "No targets selected"

        target_item = QTableWidgetItem(labels)
        target_item.setToolTip(tooltip_text)
        self.table.setItem(row, 4, target_item)

        w = sug.get("weight", 1)
        tier_item = QTableWidgetItem(f"{sug['tier'].title()} (Lvl {sug['level']}, {w}x)")
        tier_item.setToolTip(
            f"Tier: {sug['tier'].title()} | Min Level: {sug['level']} | "
            f"ChanceNone: {sug['chance']} | Weight: {w}x"
        )
        self.table.setItem(row, 5, tier_item)

    # ------------------------------------------------------------------
    def _scan_mods(self):
        self._skipped_mods.clear()
        self._extra_weap.clear()
        self._extra_armo.clear()
        mods_dir = self.organizer.modsPath()
        active_mods = {
            m for m in self.organizer.modList().allModsByProfilePriority()
            if bool(self.organizer.modList().state(m) & mobase.ModState.ACTIVE)
        }
        patched  = find_already_patched_plugins(mods_dir, active_mods=active_mods)
        ignored  = _load_ignored()
        bl_plugins, bl_mods = _load_blacklist()
        self._counts = count_all_ll_entries(mods_dir)

        inc_script = self.chk_script_inj.isChecked()
        seen_plugins = set()
        plist = self.organizer.pluginList()
        active_plugins = {
            pn.lower() for pn in plist.pluginNames()
            if bool(plist.state(pn) & 2)
        }

        for mod_name in self.organizer.modList().allModsByProfilePriority():
            if mod_name == OUTPUT_MOD_NAME or mod_name in ignored:
                continue
            if mod_name.lower() in bl_mods:
                self._skipped_mods.append((mod_name, "(all plugins)", "Listed in batch_blacklist.json"))
                continue
            if mod_name.endswith("_separator"):
                continue
            if not bool(self.organizer.modList().state(mod_name) & mobase.ModState.ACTIVE):
                continue

            mod_dir = os.path.join(mods_dir, mod_name)
            if not os.path.isdir(mod_dir):
                continue

            # MO2 / Nexus category IDs in meta.ini:
            # Gear/Creature: 5=Armor, 9=Clothing, 41=Weapons, 42=Weapons & Armor, 49=Creatures
            # Non-gear: 8=Companions, 14=Gameplay, 18=Immersion, 22=Locations, 24=Patches,
            #           26=Player Homes, 30=Quests, 34=UI, 35=Visuals, 45=Bug Fixes, 51=Framework/Modders Resources
            cats = _read_mo2_categories(mod_dir)
            _GEAR_CATS = {"5", "9", "41", "42", "49"}
            _SKIP_CATS = {"8", "22", "26", "30", "34", "35", "45", "51"}
            if cats and not (cats & _GEAR_CATS) and (cats & _SKIP_CATS):
                self._skipped_mods.append((mod_name, "(all plugins)", f"MO2/Nexus non-gear category ({','.join(sorted(cats))})"))
                continue

            for fname in sorted(os.listdir(mod_dir)):
                if not fname.lower().endswith((".esp", ".esl")):
                    continue

                if fname.lower() in bl_plugins:
                    self._skipped_mods.append((mod_name, fname, "Listed in batch_blacklist.json"))
                    continue

                if fname.lower() not in active_plugins:
                    self._skipped_mods.append((mod_name, fname, "Plugin disabled in MO2 right pane"))
                    continue
                missing_masters = [
                    m for m in (plist.masters(fname) or [])
                    if m.lower() not in active_plugins
                ]
                if missing_masters:
                    self._skipped_mods.append((mod_name, fname, f"Missing master(s): {', '.join(missing_masters)}"))
                    continue

                resolved = self.organizer.resolvePath(fname)
                plugin_path = resolved if resolved and os.path.isfile(resolved) else os.path.join(mod_dir, fname)
                parsed = parse_plugin(plugin_path)
                if not parsed:
                    if fname.lower() not in patched:
                        self._skipped_mods.append((mod_name, fname, "Failed to parse plugin"))
                    continue

                if is_protected_overhaul(fname, parsed):
                    stem = os.path.splitext(fname)[0]
                    for lv in parsed.get("root_lvli", []):
                        lbl = f"[{stem}] {lv['edid'] or lv['form_id']}"
                        fid = f"{fname}|{lv['form_id']}"
                        self._label_map[fid] = lbl
                        if lv.get("category") == "WEAP":
                            self._extra_weap.append((lbl, fid))
                        elif lv.get("category") == "ARMO":
                            self._extra_armo.append((lbl, fid))
                    if fname.lower() not in patched:
                        self._skipped_mods.append((mod_name, fname, "Faction / NPC Overhaul (auto-protected)"))
                    continue

                if fname.lower() in patched or fname.lower() in seen_plugins:
                    continue
                seen_plugins.add(fname.lower())
                if parsed.get("has_script_injector") and not inc_script:
                    self._skipped_mods.append((mod_name, fname, "Script injector quest detected"))
                    continue
                sels_check = self._get_injectable_records(parsed)
                has_injectable_gear = bool(sels_check["WEAP"] or sels_check["ARMO"])
                cell_limit = 60 if has_injectable_gear else 8

                if parsed.get("new_wrld_count", 0) > 0:
                    self._skipped_mods.append((mod_name, fname, "New worldspace (WRLD) expansion"))
                    continue
                if parsed.get("new_cell_count", 0) > cell_limit:
                    self._skipped_mods.append((mod_name, fname, f"Interior/location mod ({parsed['new_cell_count']} new cells)"))
                    continue
                if parsed.get("total_cell_edits", 0) > cell_limit:
                    self._skipped_mods.append((mod_name, fname, f"Location/dungeon mod ({parsed['total_cell_edits']} cell edits)"))
                    continue

                _STRICT_SKIP_KWS = (
                    "interiors", "interior", "player home", "playerhome",
                    "vats", "merchant", "vendor", "gambling", "vending",
                    "follower", "companion", "worldboss", "world boss", "nac.esp",
                    "settlement", "locations plus", "warehouse", "labs", "sewer",
                    "retexture", "munitions - ammo expansion", "munitions additional ammo",
                )
                _QUEST_DUNGEON_KWS = ("quest", "dungeon", "horror", "antagonist")
                low_title = f"{mod_name} {fname}".lower()
                if any(kw in low_title for kw in _STRICT_SKIP_KWS):
                    self._skipped_mods.append((mod_name, fname, "Interior/utility/retexture/ammo mod keyword"))
                    continue
                npc_cnt = len(parsed.get("npc_list", []))
                if has_injectable_gear and npc_cnt >= 4:
                    self._skipped_mods.append((mod_name, fname, f"Quest/bounty/faction mod ({npc_cnt} custom NPCs + gear)"))
                    continue
                if any(kw in low_title for kw in _QUEST_DUNGEON_KWS) and (not has_injectable_gear or npc_cnt > 2):
                    self._skipped_mods.append((mod_name, fname, "Quest/dungeon mod with custom NPCs"))
                    continue

                if parsed.get("is_attachment_addon"):
                    from .robco_engine import build_omod_slot_targets, find_obts_weapon_targets
                    omod_map, omod_labels = build_omod_slot_targets(parsed, self.organizer.resolvePath)
                    obts_targets = [] if omod_map else find_obts_weapon_targets(parsed, self.organizer.resolvePath)
                    if omod_map or obts_targets:
                        if omod_map:
                            self._label_map.update(omod_labels)
                            t_list = sorted(omod_map.keys())
                            tag_lbl = "[OMOD Addon]"
                        else:
                            t_list = []
                            for wt in obts_targets:
                                k = f"{wt['master_plugin']}|{wt['weap_fid']}"
                                m_stem, _ = os.path.splitext(wt['master_plugin'])
                                self._label_map[k] = f"[{m_stem}] {wt['weap_edid'] or wt['weap_fid']} (OBTS)"
                                t_list.append(k)
                            tag_lbl = "[OBTS Addon]"
                        sug = {
                            "targets": t_list,
                            "omod_map": omod_map,
                            "obts_targets": obts_targets,
                            "addon_path": plugin_path,
                            "confidence": "high",
                            "tier": "omod",
                            "level": 1,
                            "chance": 0,
                            "weight": 1,
                        }
                        row = self.table.rowCount()
                        self.table.insertRow(row)
                        chk = QTableWidgetItem()
                        chk.setData(QtUserRole, (mod_name, fname, parsed, sug))
                        self.table.setItem(row, 0, chk)

                        cb_wrap = QWidget()
                        cb_lay = QHBoxLayout(cb_wrap)
                        cb_lay.setContentsMargins(0, 0, 0, 0)
                        cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, "AlignmentFlag") else Qt.AlignCenter)
                        cb = QCheckBox()
                        cb.setChecked(True)
                        cb_lay.addWidget(cb)
                        self.table.setCellWidget(row, 0, cb_wrap)

                        self.table.setItem(row, 1, QTableWidgetItem(f"{mod_name} {tag_lbl}"))
                        self.table.setItem(row, 2, QTableWidgetItem(fname))
                        self._refresh_row_display(row, sug)
                    else:
                        self._skipped_mods.append((mod_name, fname, "Attachment addon (no matching master LVLI or OBTS weapon templates)"))
                    continue

                has_new_gear = bool(parsed.get("weap_families") or parsed.get("armo_list"))
                has_weap_or_armo = bool(parsed.get("root_lvli") or has_new_gear)
                has_npcs = bool(parsed.get("npc_list"))
                if not has_weap_or_armo and not has_npcs:
                    self._skipped_mods.append((mod_name, fname, "Utility/vendor/override mod (no new WEAP/ARMO/NPC_)"))
                    continue

                if not has_weap_or_armo and has_npcs:
                    combined_names = " ".join(
                        [mod_name.lower(), fname.lower()]
                        + [n.get("name", "").lower() for n in parsed.get("npc_list", [])]
                    )
                    if not any(kw in combined_names for kw in _CREATURE_KEYWORDS):
                        self._skipped_mods.append((mod_name, fname, "NPC-only interior/quest mod (no creature keywords)"))
                        continue

                if not any(self._get_injectable_records(parsed).values()):
                    self._skipped_mods.append((mod_name, fname, "No non-unique injectable records"))
                    continue

                sug_input = dict(parsed)
                if has_injectable_gear:
                    sug_input["npc_list"] = []
                sug = suggest_targets_heuristic(sug_input, self._counts)
                sug.setdefault("weight", 1)
                saved_ov = user_ovs.get(fname.lower())
                if isinstance(saved_ov, dict) and saved_ov.get("targets"):
                    sug.update(saved_ov)
                    sug["confidence"] = "high"
                if not sug["targets"]:
                    self._skipped_mods.append((mod_name, fname, "No matching vanilla target lists"))
                    continue

                row = self.table.rowCount()
                self.table.insertRow(row)

                chk = QTableWidgetItem()
                chk.setData(QtUserRole, (mod_name, fname, parsed, sug))
                self.table.setItem(row, 0, chk)

                cb_wrap = QWidget()
                cb_lay = QHBoxLayout(cb_wrap)
                cb_lay.setContentsMargins(0, 0, 0, 0)
                cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, "AlignmentFlag") else Qt.AlignCenter)
                cb = QCheckBox()
                script_ok = (not parsed.get("has_script_injector")) or inc_script
                gear_ok = (sug["confidence"] == "high") or (has_new_gear and parsed.get("total_cell_edits", 0) == 0)
                cb.setChecked(script_ok and gear_ok)
                cb_lay.addWidget(cb)
                self.table.setCellWidget(row, 0, cb_wrap)

                display_mod = f"{mod_name} [Script-Injected]" if parsed.get("has_script_injector") else mod_name
                self.table.setItem(row, 1, QTableWidgetItem(display_mod))
                self.table.setItem(row, 2, QTableWidgetItem(fname))
                self._refresh_row_display(row, sug)

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()

    # ------------------------------------------------------------------
    def _apply_batch(self):
        mods_dir = self.organizer.modsPath()
        ini_dir  = os.path.join(
            mods_dir, OUTPUT_MOD_NAME,
            "F4SE", "Plugins", "RobCo_Patcher", "leveledList",
        )
        try:
            from .robco_engine import prune_missing_masters_from_esl
            plist = self.organizer.pluginList()
            act = {pn for pn in plist.pluginNames() if bool(plist.state(pn) & 2)}
            prune_missing_masters_from_esl(os.path.join(mods_dir, OUTPUT_MOD_NAME, "RobCo_AutoSubLists.esl"), act)
            if os.path.isdir(ini_dir):
                for fn in os.listdir(ini_dir):
                    low = fn.lower()
                    if low.endswith("_robco_ll.ini"):
                        stem = fn[:-13].lower()
                    elif low.endswith("_robco_omod.ini"):
                        stem = fn[:-15].lower()
                    else:
                        continue
                    if f"{stem}.esp" not in {p.lower() for p in act} and f"{stem}.esl" not in {p.lower() for p in act}:
                        try:
                            os.remove(os.path.join(ini_dir, fn))
                        except Exception:
                            pass
        except Exception:
            pass
        written = 0
        unchecked_skipped = []
        audit_rows = []

        for row in range(self.table.rowCount()):
            chk = self.table.item(row, 0)
            cb = self._get_row_checkbox(row)
            mod_name, fname, parsed, sug = chk.data(QtUserRole)
            if not cb or not cb.isChecked():
                unchecked_skipped.append((mod_name, fname, "Unchecked in preview"))
                continue

            if sug.get("omod_map"):
                from .robco_engine import write_omod_ini
                if write_omod_ini(fname, mod_name, sug["omod_map"], ini_dir):
                    written += 1
                    stem, _ = os.path.splitext(fname)
                    injected_items = "; ".join(
                        f"[OMOD] {o.get('name') or o.get('edid') or o.get('form_id')} ({o.get('form_id')})"
                        for o in parsed.get("omod_list", [])
                    )
                    target_labels = " | ".join(self._label_map.get(t, t) for t in sug["targets"])
                    audit_rows.append([
                        f"{stem}_RobCo_OMOD.ini", mod_name, fname,
                        injected_items, target_labels, 1, 0, 1,
                    ])
                continue

            if sug.get("obts_targets"):
                from .robco_engine import inject_obts_templates
                esl_path = os.path.join(mods_dir, OUTPUT_MOD_NAME, "RobCo_AutoSubLists.esl")
                added_cnt = inject_obts_templates(
                    esl_path, parsed, sug.get("addon_path", ""),
                    sug["obts_targets"], self.organizer.resolvePath,
                )
                if added_cnt > 0:
                    written += 1
                    injected_items = "; ".join(
                        f"[OMOD] {o.get('name') or o.get('edid') or o.get('form_id')} ({o.get('form_id')})"
                        for o in parsed.get("omod_list", [])
                    )
                    target_labels = " | ".join(self._label_map.get(t, t) for t in sug["targets"])
                    audit_rows.append([
                        f"RobCo_AutoSubLists.esl (+{added_cnt} OBTS)", mod_name, fname,
                        injected_items, target_labels, 1, 0, 1,
                    ])
                continue

            selections = self._get_injectable_records(parsed)

            target_cats = sug.get("target_cats", {})
            targets = {"WEAP": [], "ARMO": [], "NPC_": []}
            for t in sug["targets"]:
                if t in target_cats:
                    targets[target_cats[t]].append(t)
                elif t in _WEAP_FIDS:
                    targets["WEAP"].append(t)
                elif t in _ARMO_FIDS:
                    targets["ARMO"].append(t)
                elif t in _NPC_FIDS:
                    targets["NPC_"].append(t)

            tier_tuple = [(int(sug["level"]), int(sug["chance"]), int(sug.get("weight", 1)))]

            if write_robco_ini(
                ini_dir, fname, mod_name,
                selections, targets,
                tier_tuple, 0,
                bundle=True,
                split_factions=True,
            ):
                written += 1
                stem = os.path.splitext(fname)[0]
                injected_items = "; ".join(
                    f"[{c}] {r.get('name') or r.get('edid') or r.get('form_id')} ({r.get('form_id')})"
                    for c in ("WEAP", "ARMO", "NPC_") for r in selections.get(c, [])
                )
                target_labels = " | ".join(self._label_map.get(t, t) for t in sug["targets"])
                audit_rows.append([
                    f"{stem}_RobCo_LL.ini", mod_name, fname,
                    injected_items, target_labels,
                    sug["level"], sug["chance"], sug.get("weight", 1),
                ])
            else:
                unchecked_skipped.append((mod_name, fname, "No non-unique injectable items"))

        report_path = os.path.join(mods_dir, OUTPUT_MOD_NAME, "RobCo_Batch_Report.csv")
        if audit_rows:
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["INI_File", "Source_Mod", "Plugin", "Injected_Items", "Injected_Into_Lists", "Min_Level", "ChanceNone", "Weight"])
                w.writerows(audit_rows)

        try:
            self.organizer.refresh()
        except Exception:
            pass

        all_skipped = self._skipped_mods + unchecked_skipped
        msg = f"Generated {written} RobCo Patcher INI file(s)."
        if audit_rows:
            msg += f"\nAudit report saved to:\n{report_path}"
        if all_skipped:
            preview_lines = "\n".join(
                f"• {m} ({p}): {reason}" for m, p, reason in all_skipped[:20]
            )
            extra = f"\n...and {len(all_skipped) - 20} more." if len(all_skipped) > 20 else ""
            msg += (
                f"\n\nSkipped {len(all_skipped)} unpatched plugin(s):\n"
                f"{preview_lines}{extra}\n\n"
                "Tip: Use 'Next Unpatched Mod >>' on Page 1 to review any remaining mods manually."
            )

        box = QMessageBox(self)
        box.setWindowTitle("Batch Complete")
        box.setText(msg)
        btn_open_csv = None
        if audit_rows and os.path.isfile(report_path):
            btn_open_csv = box.addButton("Open Audit Report (CSV)", QMessageBox.ButtonRole.ActionRole if hasattr(QMessageBox, "ButtonRole") else QMessageBox.ActionRole)
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole if hasattr(QMessageBox, "ButtonRole") else QMessageBox.AcceptRole)
        _exec_dialog(box)
        if btn_open_csv and box.clickedButton() == btn_open_csv:
            try:
                os.startfile(report_path)
            except Exception:
                pass
        self.accept()
