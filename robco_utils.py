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
    """Migrate legacy .esl, refresh MO2, auto-enable output mod/ESPs, and place at bottom of load order."""
    try:
        out_root = os.path.join(organizer.modsPath(), OUTPUT_MOD_NAME)
        legacy_esl = os.path.join(out_root, "RobCo_AutoSubLists.esl")
        if os.path.isfile(legacy_esl):
            os.remove(legacy_esl)
        ini_dir = os.path.join(out_root, "F4SE", "Plugins", "RobCo_Patcher", "leveledList")
        if os.path.isdir(ini_dir):
            for fn in os.listdir(ini_dir):
                if fn.lower().endswith("_robco_ll.ini"):
                    fp = os.path.join(ini_dir, fn)
                    txt = open(fp, "r", encoding="utf-8", errors="ignore").read()
                    if "RobCo_AutoSubLists.esl|" in txt:
                        os.remove(fp)
    except Exception:
        pass
    try:
        organizer.refresh()
        organizer.modList().setActive(OUTPUT_MOD_NAME, True)
        organizer.refresh()
    except Exception:
        pass
    try:
        import mobase
        active_flag = getattr(mobase.PluginState, "ACTIVE", 2)
        plist = organizer.pluginList()
        names = list(plist.pluginNames())
        low_map = {n.lower(): n for n in names}
        bottom = len(names)
        for offset, target in enumerate(("robco_autosublists.esp", "robco_attachmenttemplates.esp", "robco_overrideshield.esp")):
            real_name = low_map.get(target)
            if real_name:
                plist.setState(real_name, active_flag)
                try:
                    plist.setPriority(real_name, bottom + offset)
                except Exception:
                    pass
    except Exception:
        pass

def export_active_robco_inis_csv(parent):
    import configparser, csv, glob, os, re, struct
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    mo2_base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    search_roots = []

    # 1. Check MO2 organizer API if attached to wizard/parent
    org = getattr(parent, "_organizer", None) or getattr(parent.wizard(), "_organizer", None) if hasattr(parent, "wizard") and parent.wizard() else getattr(parent, "_organizer", None)
    if org is not None:
        try:
            ow = org.overwritePath()
            if ow and os.path.isdir(ow):
                search_roots.append(("Overwrite", ow))
        except Exception:
            pass
        try:
            mods_dir = org.modsPath()
            modlist = org.modList()
            for mname in modlist.allModsByProfilePriority():
                if modlist.state(mname) & 2:
                    mp = os.path.join(mods_dir, mname)
                    if os.path.isdir(mp):
                        search_roots.append((mname, mp))
        except Exception:
            pass

    # 2. Fallback: parse ModOrganizer.ini in MO2 root or %LOCALAPPDATA%\ModOrganizer
    if not search_roots:
        ini_candidates = [os.path.join(mo2_base, "ModOrganizer.ini")]
        local_mo2 = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ModOrganizer")
        if os.path.isdir(local_mo2):
            for sub in os.listdir(local_mo2):
                ini_candidates.append(os.path.join(local_mo2, sub, "ModOrganizer.ini"))
        for mini in ini_candidates:
            if os.path.isfile(mini):
                cfg = configparser.ConfigParser(interpolation=None)
                cfg.read(mini, encoding="utf-8")
                base_dir = cfg.get("Settings", "base_directory", fallback=os.path.dirname(mini)).replace("/", os.sep)
                ow_dir = cfg.get("Settings", "overwrite_directory", fallback=os.path.join(base_dir, "overwrite")).replace("%BASE_DIR%", base_dir).replace("/", os.sep)
                mods_dir = cfg.get("Settings", "mod_directory", fallback=os.path.join(base_dir, "mods")).replace("%BASE_DIR%", base_dir).replace("/", os.sep)
                if os.path.isdir(ow_dir):
                    search_roots.append(("Overwrite", ow_dir))
                if os.path.isdir(mods_dir):
                    for mname in sorted(os.listdir(mods_dir)):
                        mp = os.path.join(mods_dir, mname)
                        if os.path.isdir(mp) and os.path.isdir(os.path.join(mp, "F4SE", "Plugins", "RobCo_Patcher", "leveledList")):
                            search_roots.append((mname, mp))
                if search_roots:
                    break

    # 3. Last resort: scan immediate subdirs of MO2 base
    if not search_roots:
        ow_def = os.path.join(mo2_base, "overwrite")
        if os.path.isdir(ow_def):
            search_roots.append(("Overwrite", ow_def))

    # Resolve EditorIDs from any RobCo_AutoSubLists.esp found in search_roots
    sublist_edids = {}
    for _, root in search_roots:
        sub_esp = os.path.join(root, "RobCo_AutoSubLists.esp")
        if os.path.isfile(sub_esp):
            try:
                raw = open(sub_esp, "rb").read()
                pos = 0
                while pos + 24 <= len(raw):
                    rtype = raw[pos:pos+4]
                    rsize, = struct.unpack("<I", raw[pos+4:pos+8])
                    if rtype == b"GRUP":
                        pos += 24
                        continue
                    fid, = struct.unpack("<I", raw[pos+12:pos+16])
                    sub = raw[pos+24:pos+24+rsize]
                    sp = 0
                    while sp + 6 <= len(sub):
                        st = sub[sp:sp+4]
                        slen, = struct.unpack("<H", sub[sp+4:sp+6])
                        if st == b"EDID":
                            ed = sub[sp+6:sp+6+slen].rstrip(b"\x00").decode("utf-8", errors="ignore")
                            sublist_edids[f"0x{fid & 0xFFFFFF:06X}".upper()] = ed
                            break
                        sp += 6 + slen
                    pos += 24 + rsize
            except Exception:
                pass

    ini_files = []
    for loc_name, root in search_roots:
        ll_dir = os.path.join(root, "F4SE", "Plugins", "RobCo_Patcher", "leveledList")
        if os.path.isdir(ll_dir):
            for p in sorted(glob.glob(os.path.join(ll_dir, "*.ini"))):
                ini_files.append((loc_name, p))

    if not ini_files:
        QMessageBox.warning(parent, "No Active INIs", "Could not find any active F4SE\\Plugins\\RobCo_Patcher\\leveledList\\*.ini files in Overwrite or enabled mods.")
        return

    default_dir = os.path.dirname(os.path.abspath(__file__))
    for loc_name, root in search_roots:
        if loc_name.lower() == "robco auto-injected patches" or os.path.isfile(os.path.join(root, "RobCo_AutoSubLists.esp")):
            default_dir = root
            break
    default_out = os.path.join(default_dir, "RobCo_Active_INIs_Audit.csv")
    out_path, _ = QFileDialog.getSaveFileName(parent, "Save Active INIs CSV", default_out, "CSV Files (*.csv)")
    if not out_path:
        return

    rows = []
    for loc_name, p in ini_files:
        fn = os.path.basename(p)
        for line in open(p, encoding="utf-8", errors="ignore"):
            s = line.strip()
            if not s or s.startswith(";"):
                continue
            m = re.match(r"filterByLLs\s*=\s*([^:]+):(.+)", s, re.I)
            if not m:
                continue
            target_ll, payload = m.group(1).strip(), m.group(2).strip()
            for entry in payload.split(","):
                parts = [x.strip() for x in entry.split("|")]
                if len(parts) >= 4:
                    src_mod, fid_str, lvl, cnt = parts[0], parts[1], parts[2], parts[3]
                    norm_fid = f"0x{int(fid_str, 16) & 0xFFFFFF:06X}".upper() if fid_str.lower().startswith("0x") else fid_str
                    edid = sublist_edids.get(norm_fid, "") if src_mod.lower() == "robco_autosublists.esp" else ""
                    rows.append([loc_name, fn, target_ll, src_mod, fid_str, edid, lvl, cnt])

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Source_Location", "INI_File", "Target_LeveledList", "Injected_Plugin", "FormID", "Resolved_SubList_EDID", "Level", "Count"])
        w.writerows(rows)

    QMessageBox.information(parent, "Export Complete", f"Exported {len(rows)} active RobCo entries from {len(ini_files)} INI files to:\n{out_path}")
