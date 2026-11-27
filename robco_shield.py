"""Binary generator for RobCo_OverrideShield.esp (restores clean vanilla LVLI/LVLN records)."""

import os
import struct
from typing import Iterable, Set

from .robco_parser import find_already_patched_plugins, parse_plugin

BUILTIN_PROTECTED_OVERHAULS = {
    "wearetheminutemen.esp",
    "militarizedminutemen.esp",
    "supermutantredux.esp",
    "raideroverhaul.esp",
    "fcom.esp",
    "farharbor.esm",
    "nukaworld.esm",
    "robot.esm",
    "dlcrobot.esm",
    "dlccoast.esm",
    "dlcnukaworld.esm",
}


def is_protected_overhaul(plugin_name: str, parsed: dict = None) -> bool:
    """Returns True if a plugin is a true faction/NPC overhaul whose hierarchy should not be stripped."""
    low = plugin_name.strip().lower()
    if low in BUILTIN_PROTECTED_OVERHAULS:
        return True
    faction_kws = ("watm", "fcom", "faction", "raider", "gunner", "supermutant", "brotherhood", "institute", "minutemen", "synth", "ghoul", "creature")
    overhaul_kws = ("overhaul", "redux", "hierarchy", "expanded")
    if any(fk in low for fk in faction_kws) and any(ok in low for ok in overhaul_kws):
        return True
    if parsed and parsed.get("edits_vanilla_npcs"):
        has_own_gear = bool(parsed.get("weap_families") or parsed.get("armo_list"))
        if not has_own_gear:
            return True
    return False


def _extract_vanilla_records(esm_path: str, target_fids: Set[int]) -> dict:
    """Scan Fallout4.esm and return raw record bytes for matching LVLI/LVLN FormIDs."""
    found = {}
    if not target_fids or not os.path.isfile(esm_path):
        return found

    with open(esm_path, "rb") as f:
        data = f.read()

    if len(data) < 24 or data[0:4] != b"TES4":
        return found

    tes4_size = struct.unpack_from("<I", data, 4)[0]

    def walk(offset: int, end: int):
        while offset + 24 <= end and len(found) < len(target_fids):
            rec_type = data[offset:offset + 4]
            rec_size = struct.unpack_from("<I", data, offset + 4)[0]

            if rec_type == b"GRUP":
                grup_label = data[offset + 8:offset + 12]
                grup_type = struct.unpack_from("<i", data, offset + 12)[0]
                grup_end = min(offset + rec_size, end)
                if grup_type != 0 or grup_label in (b"LVLI", b"LVLN"):
                    walk(offset + 24, grup_end)
                offset = grup_end
                continue

            form_id = struct.unpack_from("<I", data, offset + 12)[0]
            rec_end = min(offset + 24 + rec_size, end)
            if rec_type in (b"LVLI", b"LVLN") and form_id in target_fids:
                found[form_id] = (rec_type, data[offset:rec_end])
            offset = rec_end

    walk(24 + tes4_size, len(data))
    return found


def build_override_shield(
    organizer,
    out_esp_path: str,
    whitelist_plugins: Iterable[str] = (),
) -> tuple:
    """Build RobCo_OverrideShield.esp blocking LVLI/LVLN overrides from converted plugins."""
    mods_dir = organizer.modsPath()
    patched_plugins = find_already_patched_plugins(mods_dir)
    whitelist_lower = {p.strip().lower() for p in whitelist_plugins if p.strip()}

    target_fids: Set[int] = set()
    blocked_sources = []

    for plugin_name in sorted(patched_plugins):
        low = plugin_name.lower()
        if low in whitelist_lower or low in ("fallout4.esm", "robco_autosublists.esl", "robco_overrideshield.esp"):
            continue

        resolved = organizer.resolvePath(plugin_name)
        if not resolved or not os.path.isfile(resolved):
            continue

        parsed = parse_plugin(resolved)
        if is_protected_overhaul(plugin_name, parsed):
            continue

        overrides = parsed.get("vanilla_ll_overrides", [])
        if overrides:
            blocked_sources.append(plugin_name)
            for ov in overrides:
                if "|" in ov:
                    _, hex_str = ov.split("|", 1)
                    try:
                        target_fids.add(int(hex_str, 16) & 0x00FFFFFF)
                    except ValueError:
                        pass

    if not target_fids:
        if os.path.isfile(out_esp_path):
            os.remove(out_esp_path)
        return True, 0, []

    fallout_esm = organizer.resolvePath("Fallout4.esm")
    if not fallout_esm or not os.path.isfile(fallout_esm):
        return False, 0, []

    raw_recs = _extract_vanilla_records(fallout_esm, target_fids)
    if not raw_recs:
        return False, 0, []

    lvli_blob = b"".join(raw_recs[fid][1] for fid in sorted(raw_recs) if raw_recs[fid][0] == b"LVLI")
    lvln_blob = b"".join(raw_recs[fid][1] for fid in sorted(raw_recs) if raw_recs[fid][0] == b"LVLN")

    payload = bytearray()
    if lvli_blob:
        payload += b"GRUP" + struct.pack("<I", 24 + len(lvli_blob)) + b"LVLI" + struct.pack("<III", 0, 0, 0) + lvli_blob
    if lvln_blob:
        payload += b"GRUP" + struct.pack("<I", 24 + len(lvln_blob)) + b"LVLN" + struct.pack("<III", 0, 0, 0) + lvln_blob

    hedr = b"HEDR" + struct.pack("<H", 12) + struct.pack("<fII", 1.0, len(raw_recs), 0x800)
    cnam = b"CNAM" + struct.pack("<H", 13) + b"RobCo Wizard\x00"
    mast = b"MAST" + struct.pack("<H", 13) + b"Fallout4.esm\x00"
    data_sub = b"DATA" + struct.pack("<H", 8) + struct.pack("<Q", 0)
    tes4_subs = hedr + cnam + mast + data_sub
    tes4 = b"TES4" + struct.pack("<IIIIII", len(tes4_subs), 0, 0, 0, 131, 0) + tes4_subs

    os.makedirs(os.path.dirname(out_esp_path), exist_ok=True)
    with open(out_esp_path, "wb") as f:
        f.write(tes4 + bytes(payload))

    return True, len(raw_recs), blocked_sources


def collect_overhaul_lists(organizer, exclude_plugin: str = "") -> tuple:
    """Return (extra_weap, extra_armo) tuples of (label, 'plugin.esp|0xFORMID') from active overhauls."""
    import mobase
    extra_weap, extra_armo = [], []
    excl = exclude_plugin.strip().lower()
    mods_dir = organizer.modsPath()
    try:
        for m_name in organizer.modList().allModsByProfilePriority():
            if not bool(organizer.modList().state(m_name) & mobase.ModState.ACTIVE):
                continue
            m_dir = os.path.join(mods_dir, m_name)
            if not os.path.isdir(m_dir):
                continue
            for fn in sorted(os.listdir(m_dir)):
                if not fn.lower().endswith((".esp", ".esl")) or fn.lower() == excl:
                    continue
                if is_protected_overhaul(fn):
                    res_p = organizer.resolvePath(fn)
                    ov = parse_plugin(res_p if res_p and os.path.isfile(res_p) else os.path.join(m_dir, fn))
                    stem = os.path.splitext(fn)[0]
                    for lv in ov.get("root_lvli", []):
                        entry = (f"[{stem}] {lv['edid'] or lv['form_id']}", f"{fn}|{lv['form_id']}")
                        if lv.get("category") == "WEAP":
                            extra_weap.append(entry)
                        elif lv.get("category") == "ARMO":
                            extra_armo.append(entry)
    except Exception:
        pass
    return extra_weap, extra_armo
