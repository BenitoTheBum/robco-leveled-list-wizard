"""RobCo Leveled List engine: heuristics, INI generation, and ESL bundling."""

import os
import re
from typing import Dict, List, Optional, Tuple

import struct
import zlib

def append_sublist_to_esl(esl_path, rec_type_str, edid_name):
    """Creates or appends an LVLI or LVLN record (LVLF=0x01) grouped cleanly by record type in RobCo_AutoSubLists.esp."""
    rec_tag = rec_type_str.encode("ascii")
    edid_bytes = edid_name.encode("utf-8") + b"\x00"
    edid_sub = b"EDID" + struct.pack("<H", len(edid_bytes)) + edid_bytes
    lvld_sub = b"LVLD\x01\x00\x00"
    lvlf_sub = b"LVLF\x01\x00\x01"
    sub_blob = edid_sub + lvld_sub + lvlf_sub

    records_by_type = {b"LVLI": [], b"LVLN": []}
    highest_id = 0x0007FF

    if os.path.isfile(esl_path):
        with open(esl_path, "rb") as f:
            blob = bytes(f.read())
        if len(blob) >= 24 and blob[0:4] == b"TES4":
            pos = 24 + struct.unpack("<I", blob[4:8])[0]
            while pos + 24 <= len(blob):
                tag = blob[pos:pos + 4]
                sz = struct.unpack("<I", blob[pos + 4:pos + 8])[0]
                if tag == b"GRUP":
                    pos += 24
                    continue
                fid = struct.unpack("<I", blob[pos + 12:pos + 16])[0] & 0x000FFF
                rec_bytes = blob[pos:pos + 24 + sz]
                rec_body = blob[pos + 24:pos + 24 + sz]
                if len(rec_body) >= 6 and rec_body[0:4] == b"EDID":
                    edid_len = struct.unpack("<H", rec_body[4:6])[0]
                    existing_edid = rec_body[6:6 + edid_len].rstrip(b"\x00").decode("utf-8", errors="ignore")
                    if existing_edid == edid_name:
                        return f"0x{fid:06X}"
                if fid > highest_id:
                    highest_id = fid
                if tag in records_by_type:
                    records_by_type[tag].append(rec_bytes)
                pos += 24 + sz

    next_id = highest_id + 1
    rec_hdr = rec_tag + struct.pack("<IIIIH", len(sub_blob), 0, next_id, 0, 131) + b"\x00\x00"
    records_by_type.setdefault(rec_tag, []).append(rec_hdr + sub_blob)

    total_recs = sum(len(v) for v in records_by_type.values())
    hedr = b"HEDR\x0C\x00" + struct.pack("<fII", 1.0, max(1, total_recs), next_id + 1)
    cnam = b"CNAM\x0C\x00RobCoWizard\x00"
    mast = b"MAST\x0D\x00Fallout4.esm\x00" + b"DATA\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    tes4_body = hedr + cnam + mast
    tes4_hdr = b"TES4" + struct.pack("<IIIIH", len(tes4_body), 0x00000200, 0, 0, 131) + b"\x00\x00"

    grups_blob = bytearray()
    for rtag in (b"LVLI", b"LVLN"):
        rlist = records_by_type.get(rtag, [])
        if rlist:
            payload = b"".join(rlist)
            grups_blob.extend(b"GRUP" + struct.pack("<I", 24 + len(payload)) + rtag + struct.pack("<III", 0, 0, 0) + payload)

    os.makedirs(os.path.dirname(esl_path), exist_ok=True)
    with open(esl_path, "wb") as f:
        f.write(tes4_hdr + tes4_body + bytes(grups_blob))
    return f"0x{next_id:06X}"

WEAPON_LISTS = [
    # Raiders (Hierarchy: Grunts -> Auto/Rifle -> Bosses)
    ("Raiders -> 1. Grunts & Scavengers (LLI_Raider_Weapons)", "Fallout4.esm|0x0005E8E5"),
    ("Raiders -> 2. Veterans & Auto (LLI_Raider_Auto)", "Fallout4.esm|0x0023D8CA"),
    ("Raiders -> 3. Bosses & Heavies (LLI_Raider_Weapons_Boss)", "Fallout4.esm|0x0005F42F"),
    # Gunners (Hierarchy: Semi-Auto -> Auto -> Snipers -> Bosses)
    ("Gunners -> 1. Troopers Semi-Auto (LLI_Gunner_SemiAuto)", "Fallout4.esm|0x000FD39E"),
    ("Gunners -> 2. Assault Auto (LLI_Gunner_Auto)", "Fallout4.esm|0x000FD39F"),
    ("Gunners -> 3. Marksmen & Snipers (LLI_Gunner_Sniper)", "Fallout4.esm|0x00232869"),
    ("Gunners -> 4. Commanders & Bosses (LLI_Gunner_SemiAuto_Boss)", "Fallout4.esm|0x00247551"),
    # Brotherhood of Steel
    ("Brotherhood -> 1. Initiates & Patrols (LLI_BoS_Weapons)", "Fallout4.esm|0x0007655E"),
    ("Brotherhood -> 2. Knights & Paladins (LLI_BoS_Heavy)", "Fallout4.esm|0x0007655F"),
    # Minutemen
    ("Minutemen -> 1. Militia Semi-Auto (LL_Minutemen_Weapons_NonAuto)", "Fallout4.esm|0x001BF0B8"),
    ("Minutemen -> 2. Patrols Auto (LL_Minutemen_Weapons_Auto)", "Fallout4.esm|0x001BF0B9"),
    # Railroad
    ("Railroad -> Agents & Heavies (LLI_RRAgent_Weapons)", "Fallout4.esm|0x00183303"),
    # Institute
    ("Institute -> 1. Synths Standard (LL_InstituteLaserGun)", "Fallout4.esm|0x001A7777"),
    ("Institute -> 2. Coursers & Bosses (LL_InstituteLaserGun_Boss)", "Fallout4.esm|0x001A777B"),
    # Other Factions, Vendors & Loot
    ("Triggermen -> Mobsters & Enforcers", "Fallout4.esm|0x0002B483"),
    ("Super Mutants -> 1. Skirmishers & Brutes", "Fallout4.esm|0x0004691D"),
    ("Super Mutants -> 2. Heavies (Minigun / Missile)", "Fallout4.esm|0x00109248"),
    ("Vendors -> 1. General Weapon Stores (LL_Vendor_Weapon_GunGeneralStore)", "Fallout4.esm|0x002049DD"),
    ("Vendors -> 2. Specialty Gun Shops (Arturo / KL-E-O)", "Fallout4.esm|0x0008531F"),
    ("Vendors -> 3. Brotherhood Quartermaster (Teagan)", "Fallout4.esm|0x002049DB"),
    ("Vendors -> 4. Melee & Blades (LL_Vendor_Weapon_Melee)", "Fallout4.esm|0x00153515"),
    ("Dungeon Loot -> Boss Trunks & Weapon Drops", "Fallout4.esm|0x000673AF"),
    ("Legendaries -> Legendary Weapon Pool", "Fallout4.esm|0x001CCDA9"),
]

ARMOR_LISTS = [
    # Raiders
    ("Raiders -> 1. Grunts & Scavengers", "Fallout4.esm|0x0007655A"),
    ("Raiders -> 2. Veterans & Bosses", "Fallout4.esm|0x0007655B"),
    # Gunners
    ("Gunners -> 1. Conscripts & Troopers", "Fallout4.esm|0x00058309"),
    ("Gunners -> 2. Officers & Commanders", "Fallout4.esm|0x0005830C"),
    # Brotherhood of Steel
    ("Brotherhood -> 1. Field Scribes & Lancers", "Fallout4.esm|0x0007655D"),
    ("Brotherhood -> 2. Soldiers & Recon Officers", "Fallout4.esm|0x00076563"),
    # Minutemen
    ("Minutemen -> 1. Militia Outfits (LL_Minutemen_Outfit)", "Fallout4.esm|0x000B23D2"),
    ("Minutemen -> 2. Armored Gear (LL_Minutemen_Armored)", "Fallout4.esm|0x001BF0CC"),
    # Railroad
    ("Railroad -> 1. Agent Armored Coats (LLI_Armor_RRAgent)", "Fallout4.esm|0x0018330B"),
    ("Railroad -> 2. Undercover Clothing (LL_Railroad_ClothingArmor)", "Fallout4.esm|0x0020DE46"),
    # Institute
    ("Institute -> 1. Synth Armor Sets (LL_Armor_Synth_Set_Full)", "Fallout4.esm|0x0022E2FB"),
    ("Institute -> 2. Lab Coats & Uniforms (LL_Clothes_Institute)", "Fallout4.esm|0x001A6B10"),
    # Other Factions, Power Armor, Vendors & Loot
    ("Children of Atom -> Robes & Gear (LLI_ChildrenOfAtom_Clothes)", "Fallout4.esm|0x0022CDF1"),
    ("Diamond City -> Security Gear", "Fallout4.esm|0x0002332F"),
    ("Triggermen -> Suits & Fedoras", "Fallout4.esm|0x000EBE8E"),
    ("Power Armor -> 1. World & Boss Frames (LL_Armor_Power_Set)", "Fallout4.esm|0x0018AE53"),
    ("Power Armor -> 2. Power Armor Vendors (Atom Cats / BoS)", "Fallout4.esm|0x00137824"),
    ("Wastelanders -> Settlers & Minutemen", "Fallout4.esm|0x000330F4"),
    ("Vendors -> 1. General Armor & Clothing Stores", "Fallout4.esm|0x0007645A"),
    ("Vendors -> 2. Armor Merchants (LL_Vendor_Armor)", "Fallout4.esm|0x00240100"),
    ("Dungeon Loot -> Boss Trunks", "Fallout4.esm|0x0007645B"),
    ("Legendaries -> Legendary Armor Pool", "Fallout4.esm|0x001CCDAA"),
]

CREATURE_LISTS: List[Tuple[str, str]] = [
    ("Commonwealth -> Wildlife (Radstag / Yao Guai)", "Fallout4.esm|0x0002059B"),
    ("Commonwealth -> Deathclaw Encounters (LCharDeathclaw)", "Fallout4.esm|0x0007533D"),
    ("Super Mutants -> Ranged & Assault Encounters", "Fallout4.esm|0x001478BC"),
    ("Super Mutants -> Behemoths (LCharSMBehemoth)", "Fallout4.esm|0x0012B97D"),
    ("Urban / Ruins -> Feral Ghoul Packs", "Fallout4.esm|0x0002059C"),
    ("Coastal / Swamp -> Mirelurk Spawns", "Fallout4.esm|0x0002059D"),
    ("Glowing Sea -> Apex Predators", "Fallout4.esm|0x000A0EE7"),
    ("Wasteland -> Insects & Radscorpions", "Fallout4.esm|0x0002059A"),
    ("Robots -> Sentry Bots (LCharSentryBot)", "Fallout4.esm|0x0012BC12"),
    ("Robots -> Assaultrons (LCharAssaultron)", "Fallout4.esm|0x00121D51"),
]

_FID_TO_LABEL: Dict[str, str] = {
    fid: lbl for lbl, fid in WEAPON_LISTS + ARMOR_LISTS + CREATURE_LISTS
}

_WEAPON_FIDS   = {fid for _, fid in WEAPON_LISTS}
_ARMOR_FIDS    = {fid for _, fid in ARMOR_LISTS}

_TIERS = {
    "early": {"tier": "early", "level": 1,  "chance": 0},
    "mid":   {"tier": "mid",   "level": 15, "chance": 25},
    "late":  {"tier": "late",  "level": 30, "chance": 50},
}


def count_all_ll_entries(mods_dir: str) -> Dict[str, int]:
    """Scan all RobCo Patcher INI files and tally entries per target list in O(1) per line."""
    counts: Dict[str, int] = {}
    if not os.path.isdir(mods_dir):
        return counts

    low_to_canon = {fid.lower(): fid for fid in _FID_TO_LABEL}
    pattern = re.compile(r"filterByLLs=([^:|]+\.(?:esm|esp|esl)\|0x[0-9A-Fa-f]+):addToLLs=", re.IGNORECASE)
    for mod_folder in os.listdir(mods_dir):
        ll_dir = os.path.join(mods_dir, mod_folder, "F4SE", "Plugins", "RobCo_Patcher", "leveledList")
        if not os.path.isdir(ll_dir):
            continue
        for fname in os.listdir(ll_dir):
            if not fname.lower().endswith(".ini"):
                continue
            try:
                with open(os.path.join(ll_dir, fname), "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        s = line.strip()
                        if not s or s.startswith(";"):
                            continue
                        m = pattern.search(s)
                        if m:
                            canon = low_to_canon.get(m.group(1).lower())
                            if canon:
                                counts[canon] = counts.get(canon, 0) + 1
            except Exception:
                pass
    return counts


def suggest_targets_heuristic(parsed: dict, counts: Dict[str, int]) -> dict:
    """Heuristically suggest matching faction/rank vanilla leveled lists."""
    targets: List[str] = []
    matched_specific = False

    def _add_if_open(fid: str):
        if fid not in targets and counts.get(fid, 0) < 245:
            targets.append(fid)

    valid_target_ids = {f for _, f in (WEAPON_LISTS + ARMOR_LISTS + CREATURE_LISTS)}
    for ov_fid in parsed.get("vanilla_ll_overrides", []):
        if ov_fid in valid_target_ids:
            _add_if_open(ov_fid)
            matched_specific = True

    plugin_low = parsed.get("plugin_name", "").lower()
    weap_recs = [r for r in parsed.get("root_lvli", []) if r.get("category") == "WEAP"] + parsed.get("weap_families", [])
    armo_recs = [r for r in parsed.get("root_lvli", []) if r.get("category") == "ARMO"] + parsed.get("armo_list", [])
    npc_recs  = parsed.get("npc_list", [])

    for r in weap_recs:
        raw_nm = r.get("name", "").lower()
        txt = f"{raw_nm} {r.get('edid', '').lower()} {plugin_low}"

        # 1. Explicit faction-configured weapon variants (checked first)
        if any(k in txt for k in ("bos", "brotherhood", "paladin", "knight", "enclave")):
            _add_if_open("Fallout4.esm|0x0007655E")
            _add_if_open("Fallout4.esm|0x0007655F")
            matched_specific = True
        elif any(k in txt for k in ("gunner", "merc")):
            _add_if_open("Fallout4.esm|0x000FD39E")
            _add_if_open("Fallout4.esm|0x000FD39F")
            matched_specific = True
        elif any(k in txt for k in ("musket", "minutemen", "minuteman", "crank", "militia")):
            _add_if_open("Fallout4.esm|0x001BF0B8")
            matched_specific = True
        elif any(k in txt for k in ("railroad", "railway", "deliverer", "tinker")):
            _add_if_open("Fallout4.esm|0x00183303")
            matched_specific = True
        elif any(k in txt for k in ("institute", "synth", "courser")):
            _add_if_open("Fallout4.esm|0x001A7777")
            matched_specific = True
        elif any(k in txt for k in ("centaur", "supermutant", "super_mutant", "mutant")):
            _add_if_open("Fallout4.esm|0x0004691D")
            matched_specific = True
        elif any(k in txt for k in ("triggerman", "mobster", "mafia")):
            _add_if_open("Fallout4.esm|0x0002B483")
            matched_specific = True
        # 2. General weapon-type heuristics
        elif any(k in txt for k in ("sword", "blade", "knife", "machete", "sledge", "hammer", "katana", "spear", "melee", "fist", "knuckle", "hatchet", "pickaxe", "tonfa")) or re.search(r"\b(axe|bat)\b", txt):
            _add_if_open("Fallout4.esm|0x00153515")
            _add_if_open("Fallout4.esm|0x0005E8E5")
            matched_specific = True
        elif any(k in txt for k in ("raider", "pipe", "pistol", "revolver", "10mm", ".44", "9mm", "smg", "submachine", ".45")):
            _add_if_open("Fallout4.esm|0x0005E8E5")
            _add_if_open("Fallout4.esm|0x0002B483")
            matched_specific = True
        elif any(k in txt for k in ("sniper", "marksman", "hunting", ".50", "amr", "anti")):
            _add_if_open("Fallout4.esm|0x00232869")
            matched_specific = True
        elif any(k in txt for k in ("laser", "plasma", "gatling", "tesla")):
            _add_if_open("Fallout4.esm|0x0007655E")
            _add_if_open("Fallout4.esm|0x0007655F")
            matched_specific = True
        elif any(k in txt for k in ("minigun", "missile", "fatman", "launcher", "heavy")):
            _add_if_open("Fallout4.esm|0x0005F42F")
            _add_if_open("Fallout4.esm|0x00109248")
            matched_specific = True
        elif any(k in txt for k in ("rifle", "shotgun", "assault", "carbine", "ak", "m4", "m16", "service", "fal", "g3", "sks", "sturmgewehr", "stg", "scar", "galil", "ruger", "lever", "repeater", "bren", "lmg")):
            _add_if_open("Fallout4.esm|0x0023D8CA")
            _add_if_open("Fallout4.esm|0x000FD39F")
            matched_specific = True
    if weap_recs and not any(t in _WEAPON_FIDS for t in targets):
        _add_if_open("Fallout4.esm|0x000FD39E")
        _add_if_open("Fallout4.esm|0x002049DD")

    _PA_KEYWORDS = (
        "power armor", "powerarmor", "power_armor", "_power_", "ll_armor_power",
        "t-45", "t45", "t-51", "t51", "t-60", "t60", "t-65", "t65",
        "x-01", "x01", "x-02", "x02", "hellcat", "excavator", "ultracite", "equalizer",
    )
    has_power_armor = any(k in plugin_low for k in _PA_KEYWORDS)

    for r in armo_recs:
        txt = f"{r.get('name', '')} {r.get('edid', '')} {plugin_low}".lower()
        is_pa = any(k in txt for k in _PA_KEYWORDS)
        if is_pa and (len(armo_recs) <= 15 or any(k in plugin_low for k in _PA_KEYWORDS)):
            has_power_armor = True
            _add_if_open("Fallout4.esm|0x0018AE53")
            _add_if_open("Fallout4.esm|0x00137824")
            matched_specific = True
            continue

        if any(k in txt for k in ("raider", "scrap", "cage", "harness", "bandit", "overboss")):
            _add_if_open("Fallout4.esm|0x0007655A")
            matched_specific = True
        elif any(k in txt for k in ("bos", "brotherhood", "scribe", "lancer", "recon", "paladin", "knight", "sentinel", "enclave")):
            _add_if_open("Fallout4.esm|0x0007655D")
            matched_specific = True
        elif any(k in txt for k in ("combat", "tactical", "merc", "gunner", "military", "rig")):
            _add_if_open("Fallout4.esm|0x00058309")
            matched_specific = True
        elif any(k in txt for k in ("minutemen", "minuteman", "militia", "colonial")):
            _add_if_open("Fallout4.esm|0x000B23D2")
            _add_if_open("Fallout4.esm|0x001BF0CC")
            matched_specific = True
        elif any(k in txt for k in ("railroad", "agent")):
            _add_if_open("Fallout4.esm|0x0018330B")
            matched_specific = True
        elif any(k in txt for k in ("institute", "synth", "courser")):
            _add_if_open("Fallout4.esm|0x0022E2FB")
            matched_specific = True
        elif any(k in txt for k in ("children of atom", "atom", "zealot")):
            _add_if_open("Fallout4.esm|0x0022CDF1")
            matched_specific = True
        elif any(k in txt for k in ("vault", "settler", "casual", "coat", "jacket", "wasteland")):
            _add_if_open("Fallout4.esm|0x000330F4")
            matched_specific = True

    if armo_recs and not any(t in _ARMOR_FIDS for t in targets):
        if has_power_armor:
            _add_if_open("Fallout4.esm|0x0018AE53")
            _add_if_open("Fallout4.esm|0x00137824")
        else:
            _add_if_open("Fallout4.esm|0x000330F4")
            _add_if_open("Fallout4.esm|0x0007645A")

    for r in npc_recs:
        txt = f"{r.get('name', '')} {r.get('edid', '')} {plugin_low}".lower()
        if any(k in txt for k in ("behemoth",)):
            _add_if_open("Fallout4.esm|0x0012B97D")
            matched_specific = True
        elif any(k in txt for k in ("supermutant", "super mutant", "mutant", "nightkin", "centaur")):
            _add_if_open("Fallout4.esm|0x001478BC")
            matched_specific = True
        elif any(k in txt for k in ("deathclaw",)):
            _add_if_open("Fallout4.esm|0x0007533D")
            matched_specific = True
        elif any(k in txt for k in ("sentry",)):
            _add_if_open("Fallout4.esm|0x0012BC12")
            matched_specific = True
        elif any(k in txt for k in ("assaultron",)):
            _add_if_open("Fallout4.esm|0x00121D51")
            matched_specific = True
        elif any(k in txt for k in ("ghoul", "feral", "zombie")):
            _add_if_open("Fallout4.esm|0x0002059C")
            matched_specific = True
        elif any(k in txt for k in ("mirelurk", "crab", "lurk", "swamp")):
            _add_if_open("Fallout4.esm|0x0002059D")
            matched_specific = True
        elif any(k in txt for k in ("radscorpion", "glowing")):
            _add_if_open("Fallout4.esm|0x000A0EE7")
            matched_specific = True
        elif any(k in txt for k in ("insect", "roach", "fly", "stingwing", "bloodbug", "mantis")):
            _add_if_open("Fallout4.esm|0x0002059A")
            matched_specific = True
        elif any(k in txt for k in ("radstag", "yao guai", "yaoguai", "brahmin", "dog", "hound", "molerat", "mole rat", "gecko", "creature", "animal", "wildlife")):
            _add_if_open("Fallout4.esm|0x0002059B")
            matched_specific = True

    allowed_fids = set()
    if weap_recs:
        allowed_fids |= _WEAPON_FIDS
    if armo_recs:
        allowed_fids |= _ARMOR_FIDS
    if npc_recs and not weap_recs and not armo_recs:
        allowed_fids |= {fid for _, fid in CREATURE_LISTS}
    if allowed_fids:
        targets = [t for t in targets if t in allowed_fids]

    if matched_specific or parsed.get("root_lvli"):
        confidence = "high"
    elif targets:
        confidence = "medium"
    else:
        confidence = "low"

    all_names = " ".join(
        f"{r.get('name', '')} {r.get('edid', '')}" for r in (weap_recs + armo_recs + npc_recs)
    ).lower() + " " + plugin_low
    is_rifle_class = any(kw in all_names for kw in ("assault", "rifle", "shotgun", "carbine", "ak", "ar15", "m4", "m16", "fal", "g3", "sks", "stg", "scar", "galil"))
    if any(kw in all_names for kw in ("endgame", "gauss", "anti-materiel", "anti materiel", "20mm", "fatman", "fat man", "whalegun")):
        tier_def = _TIERS["late"]
    elif is_rifle_class:
        tier_def = {"tier": "custom", "level": 8, "chance": 45}
    elif any(kw in all_names for kw in ("combat", "laser", "plasma", "sniper", "heavy", "power")):
        tier_def = _TIERS["mid"]
    else:
        tier_def = _TIERS["early"]

    lvlo_levels = parsed.get("lvlo_levels", [])
    if lvlo_levels and max(lvlo_levels) > 1:
        detected_lvl = min(l for l in lvlo_levels if l > 1)
        tier_key = "late" if detected_lvl >= 25 else ("mid" if detected_lvl >= 12 else "early")
        tier_def = {"tier": "custom", "level": detected_lvl, "chance": _TIERS[tier_key]["chance"]}

    is_creature_with_skins = bool(
        npc_recs and not weap_recs
        and not any(r.get("category") == "ARMO" for r in parsed.get("root_lvli", []))
        and any(k in plugin_low for k in ("centaur", "creature", "monster", "mutant", "ghoul", "deathclaw", "mirelurk", "radscorpion", "hound", "beast"))
    )
    if is_creature_with_skins:
        armo_recs = []
    if npc_recs and not weap_recs and not armo_recs and "centaur" in plugin_low:
        targets = ["Fallout4.esm|0x001478BC"]

    _cat_allowed = set()
    if weap_recs:
        _cat_allowed |= _WEAPON_FIDS
    if armo_recs:
        _cat_allowed |= _ARMOR_FIDS
    if npc_recs and not weap_recs and not armo_recs:
        _cat_allowed |= {fid for _, fid in CREATURE_LISTS}
    if _cat_allowed:
        targets = [t for t in targets if t in _cat_allowed]
    if npc_recs and not weap_recs and not armo_recs and not targets:
        _add_if_open("Fallout4.esm|0x0002059B")

    if "Fallout4.esm|0x0023D8CA" in targets and "Fallout4.esm|0x0005E8E5" in targets:
        targets.remove("Fallout4.esm|0x0005E8E5")

    return {
        "targets":    targets,
        "confidence": confidence,
        "tier":       tier_def["tier"],
        "level":      tier_def["level"],
        "chance":     tier_def["chance"],
    }


def _expand_records(records: list) -> list:
    concrete = []
    for rec in records:
        if rec.get("type") == "WEAP_FAMILY" and rec.get("members"):
            non_unique = [m for m in rec["members"] if not m.get("is_unique")]
            concrete.extend(non_unique if non_unique else rec["members"])
        else:
            concrete.append(rec)
    return concrete


_FACTION_BUCKETS = [
    ("Gunners",      ("gunner", "merc"),                                                        {"Fallout4.esm|0x000FD39E", "Fallout4.esm|0x000FD39F", "Fallout4.esm|0x00232869", "Fallout4.esm|0x00247551", "Fallout4.esm|0x00058309", "Fallout4.esm|0x0005830C"}),
    ("Brotherhood",  ("bos", "brotherhood", "paladin", "knight", "scribe", "lancer", "sentinel"), {"Fallout4.esm|0x0007655E", "Fallout4.esm|0x0007655F", "Fallout4.esm|0x0007655D", "Fallout4.esm|0x0018AE53", "Fallout4.esm|0x00076563"}),
    ("Minutemen",    ("minutemen", "minuteman", "militia", "musket", "crank"),                  {"Fallout4.esm|0x001BF0B8", "Fallout4.esm|0x001BF0B9", "Fallout4.esm|0x000B23D2", "Fallout4.esm|0x001BF0CC"}),
    ("Railroad",     ("railroad", "railway", "deliverer", "tinker", "agent"),                   {"Fallout4.esm|0x00183303", "Fallout4.esm|0x0018330B", "Fallout4.esm|0x0020DE46"}),
    ("Institute",    ("institute", "synth", "courser"),                                         {"Fallout4.esm|0x001A7777", "Fallout4.esm|0x001A777B", "Fallout4.esm|0x0022E2FB", "Fallout4.esm|0x001A6B10"}),
    ("Raiders",      ("raider", "scrap", "cage", "harness", "bandit", "overboss"),              {"Fallout4.esm|0x0005E8E5", "Fallout4.esm|0x0023D8CA", "Fallout4.esm|0x0005F42F", "Fallout4.esm|0x0007655A", "Fallout4.esm|0x0007655B"}),
    ("SuperMutants", ("supermutant", "super_mutant", "mutant"),                                 {"Fallout4.esm|0x0004691D", "Fallout4.esm|0x00109248"}),
    ("Triggermen",   ("triggerman", "mobster", "mafia"),                                        {"Fallout4.esm|0x0002B483", "Fallout4.esm|0x000EBE8E"}),
    ("ChildrenOfAtom", ("children of atom", "atom", "radium", "gamma", "zealot"),              {"Fallout4.esm|0x0022CDF1"}),
]


def _classify_item_faction(rec: dict, plugin_hint: str = "") -> str:
    txt = f"{rec.get('name', '')} {rec.get('edid', '')}".lower()
    for fac_name, kws, _ in _FACTION_BUCKETS:
        if any(k in txt for k in kws):
            return fac_name
    if plugin_hint:
        p_low = plugin_hint.lower()
        for fac_name, kws, _ in _FACTION_BUCKETS:
            if any(k in p_low for k in kws):
                return fac_name
    return "General"


def _filter_targets_for_faction(target_list: List[str], fac_name: str) -> List[str]:
    if fac_name == "General":
        return target_list
    fac_fids = next((fids for name, _, fids in _FACTION_BUCKETS if name == fac_name), set())
    matched = [t for t in target_list if t in fac_fids or fac_name.lower() in t.lower()]
    return matched if matched else target_list


def write_robco_ini(
    ini_dir: str,
    plugin_fname: str,
    mod_name: str,
    selections: dict,
    targets: dict,
    level,
    chance: int = 0,
    bundle: bool = True,
    split_factions: bool = False,
) -> bool:
    """Write a valid RobCo Patcher leveledList INI file (supports multi-tier, weights & faction splitting)."""
    try:
        os.makedirs(ini_dir, exist_ok=True)
        plugin_stem = os.path.splitext(plugin_fname)[0]
        ini_path = os.path.join(ini_dir, f"{plugin_stem}_RobCo_LL.ini")

        out_mod_root = os.path.abspath(os.path.join(ini_dir, "..", "..", "..", ".."))
        esl_name = "RobCo_AutoSubLists.esp"
        esl_path = os.path.join(out_mod_root, esl_name)

        raw_tiers = level if isinstance(level, list) else [(int(level), int(chance), 1)]
        tiers = [(t[0], t[1], t[2] if len(t) > 2 else 1) for t in raw_tiers]

        lines: List[str] = [
            f"; RobCo Patcher leveled list patch for {mod_name} ({plugin_fname})",
            "; Generated by RobCo Leveled List Wizard",
            "",
        ]

        wrote_any = False
        injected_sublists_by_target = set()
        for category, raw_records in selections.items():
            cat_targets = targets.get(category, [])
            if not raw_records or not cat_targets:
                continue

            records = _expand_records(raw_records)
            if not records:
                continue

            if split_factions and category in ("WEAP", "ARMO"):
                buckets: Dict[str, list] = {}
                for rec in records:
                    fac = _classify_item_faction(rec, plugin_fname)
                    buckets.setdefault(fac, []).append(rec)
            else:
                buckets = {"General": records}

            for fac_name, fac_records in buckets.items():
                fac_targets = _filter_targets_for_faction(cat_targets, fac_name)
                if not fac_targets:
                    continue

                wrote_any = True
                suffix = f"_{fac_name}" if fac_name != "General" else ""
                lines.append(f"; --- {category} ({fac_name}) ---")
                is_single_lvli = (len(fac_records) == 1 and fac_records[0].get("type") == "LVLI")

                if bundle and len(fac_records) > 1 and not is_single_lvli:
                    edid_name = f"RobCo_{plugin_stem}_{category}{suffix}"
                    rec_type = "LVLN" if category == "NPC_" else "LVLI"
                    sub_fid = append_sublist_to_esl(esl_path, rec_type, edid_name)

                    for rec in fac_records:
                        lines.append(
                            f"filterByLLs={esl_name}|{sub_fid}:addToLLs={plugin_fname}|{rec['form_id']}~1~1~0"
                        )
                    for lvl, chg, weight in tiers:
                        for _ in range(weight):
                            for target_fid in fac_targets:
                                dedup_key = (target_fid.lower(), sub_fid.lower(), lvl, chg)
                                if fac_name == "General" and any(k[0] == target_fid.lower() and k[2] == lvl for k in injected_sublists_by_target):
                                    continue
                                injected_sublists_by_target.add(dedup_key)
                                lines.append(
                                    f"filterByLLs={target_fid}:addToLLs={esl_name}|{sub_fid}~{lvl}~1~{chg}"
                                )
                else:
                    for lvl, chg, weight in tiers:
                        for _ in range(weight):
                            for rec in fac_records:
                                for target_fid in fac_targets:
                                    lines.append(
                                        f"filterByLLs={target_fid}:addToLLs={plugin_fname}|{rec['form_id']}~{lvl}~1~{chg}"
                                    )
                lines.append("")

        if not wrote_any:
            return False

        with open(ini_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return True

    except Exception as exc:
        print(f"[RobCo] write_robco_ini error: {exc}")
        return False



_AP_KYWD_TO_SLOT: Dict[str, str] = {
    "Fallout4.esm|0x00022499": "scope",      # ap_gun_Scope
    "Fallout4.esm|0x00024F55": "muzzle",     # ap_gun_Muzzle
    "Fallout4.esm|0x00024F56": "barrel",     # ap_gun_Barrel
    "Fallout4.esm|0x00024F57": "grip",       # ap_gun_Grip
    "Fallout4.esm|0x00024F58": "magazine",   # ap_gun_Magazine
    "Fallout4.esm|0x0005E5B4": "receiver",   # ap_gun_Receiver
    "Fallout4.esm|0x00185B40": "material",   # ap_gun_Material
}

_SLOT_KEYWORDS: Dict[str, tuple] = {
    "scope":    ("scope", "optic", "sight", "reflex", "recon"),
    "muzzle":   ("muzzle", "suppressor", "silencer", "comp", "brake", "bayonet"),
    "barrel":   ("barrel", "handguard", "shroud"),
    "grip":     ("grip", "stock", "chassis"),
    "magazine": ("mag", "magazine", "drum", "clip"),
    "receiver": ("receiver", "auto", "semi", "bolt", "caliber", "chamber"),
    "material": ("material", "paint", "skin", "camo", "finish"),
}


def _infer_omod_slot(omod: dict) -> str:
    ap = omod.get("attach_point", "")
    if ap in _AP_KYWD_TO_SLOT:
        return _AP_KYWD_TO_SLOT[ap]
    blob = f"{omod.get('edid', '')} {omod.get('name', '')}".lower()
    for slot, kws in _SLOT_KEYWORDS.items():
        if any(k in blob for k in kws):
            return slot
    return ""


def build_omod_slot_targets(addon_parsed: dict, resolve_plugin_fn) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """Map attachment addon OMOD FormIDs onto matching attachment LVLIs in master weapon plugins."""
    try:
        from .robco_parser import parse_plugin
    except ImportError:
        from robco_parser import parse_plugin

    omods = addon_parsed.get("omod_list", [])
    if not omods:
        return {}, {}

    vanilla_masters = {
        "fallout4.esm", "dlcrobot.esm", "dlcworkshop01.esm",
        "dlccoast.esm", "dlcworkshop02.esm", "dlcworkshop03.esm", "dlcnukaworld.esm",
        "munitions - an ammo expansion.esl", "munitions additional ammo redux.esl", "tacticalreload.esm", "metroweaponframework.esl",
    }
    custom_masters = [m for m in addon_parsed.get("masters", []) if m.lower() not in vanilla_masters]

    slot_to_lvlis: Dict[str, List[str]] = {}
    lvli_labels: Dict[str, str] = {}
    for mast in custom_masters:
        m_path = resolve_plugin_fn(mast)
        if not m_path or not os.path.isfile(m_path):
            continue
        mp = parse_plugin(m_path)
        stem = os.path.splitext(mp["plugin_name"])[0]
        for lv in mp.get("lvli_list", []):
            if lv.get("category") != "OMOD_LIST":
                continue
            ed = (lv.get("edid") or "").lower()
            full_fid = f"{mp['plugin_name']}|{lv['form_id']}"
            lvli_labels[full_fid] = f"[{stem}] {lv.get('edid') or lv['form_id']}"
            for slot, kws in _SLOT_KEYWORDS.items():
                if any(k in ed for k in kws):
                    slot_to_lvlis.setdefault(slot, []).append(full_fid)

    if not slot_to_lvlis:
        return {}, {}

    target_to_omods: Dict[str, List[str]] = {}
    for om in omods:
        slot = _infer_omod_slot(om)
        if not slot or slot not in slot_to_lvlis:
            continue
        om_fid = f"{addon_parsed['plugin_name']}|{om['form_id']}"
        for tgt_lvli in slot_to_lvlis[slot]:
            target_to_omods.setdefault(tgt_lvli, []).append(om_fid)
    return target_to_omods, lvli_labels


def write_omod_ini(addon_plugin: str, mod_name: str, target_to_omods: Dict[str, List[str]], ini_dir: str) -> bool:
    """Write RobCo Patcher leveledList INI injecting OMODs into base weapon attachment LVLIs."""
    if not target_to_omods:
        return False
    os.makedirs(ini_dir, exist_ok=True)
    stem = os.path.splitext(addon_plugin)[0]
    ini_path = os.path.join(ini_dir, f"{stem}_RobCo_OMOD.ini")
    lines = [
        f"; RobCo Patcher OMOD attachment slot patch for {mod_name} ({addon_plugin})",
        "; Generated by RobCo Leveled List Wizard (Part 1 OMOD Injector)",
        "",
    ]
    for tgt_lvli, omod_fids in sorted(target_to_omods.items()):
        for om in omod_fids:
            lines.append(f"filterByLLs={tgt_lvli}:addToLLs={om}~1~1~0")
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return True


def _iter_subs_raw(body: bytes):
    p = 0
    n = len(body)
    while p + 6 <= n:
        stype = body[p:p+4]
        ssz, = struct.unpack("<H", body[p+4:p+6])
        if stype == b"XXXX" and ssz == 4 and p + 10 <= n:
            big_sz, = struct.unpack("<I", body[p+6:p+10])
            p += 10
            if p + 6 <= n:
                stype = body[p:p+4]
                p += 6
                yield stype, body[p:p+big_sz], True
                p += big_sz
            continue
        yield stype, body[p+6:p+6+ssz], False
        p += 6 + ssz


def _remap_fid(fid: int, src_masters: List[str], dst_masters: List[str]) -> int:
    if fid == 0:
        return 0
    idx = fid >> 24
    low = fid & 0x00FFFFFF
    owner = src_masters[idx] if idx < len(src_masters) else src_masters[-1]
    owner_low = owner.lower()
    for d_idx, dm in enumerate(dst_masters):
        if dm.lower() == owner_low:
            return (d_idx << 24) | low
    dst_masters.append(owner)
    return ((len(dst_masters) - 1) << 24) | low


def _remap_obts_blob(obts: bytes, src_masters: List[str], dst_masters: List[str]) -> bytearray:
    buf = bytearray(obts)
    if len(buf) < 18:
        return buf
    att_cnt, = struct.unpack("<I", buf[0:4])
    kw_cnt = buf[15]
    pos = 16
    for _ in range(kw_cnt):
        if pos + 4 <= len(buf):
            kf, = struct.unpack("<I", buf[pos:pos+4])
            buf[pos:pos+4] = struct.pack("<I", _remap_fid(kf, src_masters, dst_masters))
        pos += 4
    pos += 2
    for _ in range(att_cnt):
        if pos + 7 <= len(buf):
            ofid, = struct.unpack("<I", buf[pos:pos+4])
            buf[pos:pos+4] = struct.pack("<I", _remap_fid(ofid, src_masters, dst_masters))
        pos += 7
    return buf


def find_obts_weapon_targets(addon_parsed: dict, resolve_plugin_fn) -> List[dict]:
    """Find non-unique base WEAP records in custom masters that use OBTS templates."""
    try:
        from .robco_parser import parse_plugin
    except ImportError:
        from robco_parser import parse_plugin

    if not addon_parsed.get("omod_list"):
        return []
    vanilla = {
        "fallout4.esm", "dlcrobot.esm", "dlcworkshop01.esm",
        "dlccoast.esm", "dlcworkshop02.esm", "dlcworkshop03.esm", "dlcnukaworld.esm",
        "munitions - an ammo expansion.esl", "munitions additional ammo redux.esl", "tacticalreload.esm", "metroweaponframework.esl",
    }
    custom_masters = [m for m in addon_parsed.get("masters", []) if m.lower() not in vanilla]
    targets = []
    for mast in custom_masters:
        m_path = resolve_plugin_fn(mast)
        if not m_path or not os.path.isfile(m_path):
            continue
        mp = parse_plugin(m_path)
        for fam in mp.get("weap_families", []):
            for mem in fam.get("members", []):
                if mem.get("is_unique"):
                    continue
                if (mem.get("templates", 0) or mem.get("template_count", 0)) > 0:
                    targets.append({
                        "master_plugin": mp["plugin_name"],
                        "master_path": m_path,
                        "weap_fid": mem["form_id"],
                        "weap_edid": mem.get("edid", ""),
                        "weap_name": mem.get("name", ""),
                    })
    return targets


def inject_obts_templates(esl_path: str, addon_parsed: dict, addon_path: str,
                          obts_targets: List[dict], resolve_plugin_fn) -> int:
    """Clone base WEAP records into ESL-flagged RobCo_AttachmentTemplates.esp and append addon OMODs to OBTS."""
    omods = [o for o in addon_parsed.get("omod_list", []) if o.get("attach_point")]
    if not omods or not obts_targets:
        return 0

    addon_plug = addon_parsed["plugin_name"]
    existing_masters: List[str] = ["Fallout4.esm"]
    existing_weaps: Dict[int, bytes] = {}

    if os.path.isfile(esl_path):
        with open(esl_path, "rb") as f:
            blob = f.read()
        if len(blob) >= 24 and blob[0:4] == b"TES4":
            tsz, = struct.unpack("<I", blob[4:8])
            existing_masters = []
            for st, sb, _ in _iter_subs_raw(blob[24:24 + tsz]):
                if st == b"MAST":
                    existing_masters.append(sb.rstrip(b"\x00").decode("utf-8", "ignore"))
            if not existing_masters:
                existing_masters = ["Fallout4.esm"]
            off = 24 + tsz
            while off + 24 <= len(blob):
                rt = blob[off:off+4]
                rsz, = struct.unpack("<I", blob[off+4:off+8])
                if rt == b"GRUP":
                    off += 24
                    continue
                if rt == b"WEAP":
                    fid, = struct.unpack("<I", blob[off+12:off+16])
                    existing_weaps[fid] = blob[off:off+24+rsz]
                off += 24 + rsz

    def _ensure_master(m_name: str) -> int:
        low = m_name.lower()
        for idx, em in enumerate(existing_masters):
            if em.lower() == low:
                return idx
        existing_masters.append(m_name)
        return len(existing_masters) - 1

    addon_m_idx = _ensure_master(addon_plug)
    added_pairs = 0
    by_master: Dict[str, List[dict]] = {}
    for wt in obts_targets:
        by_master.setdefault(wt["master_plugin"], []).append(wt)

    for m_plug, w_list in by_master.items():
        m_path = resolve_plugin_fn(m_plug)
        if not m_path or not os.path.isfile(m_path):
            continue
        with open(m_path, "rb") as f:
            m_blob = f.read()
        if len(m_blob) < 24 or m_blob[0:4] != b"TES4":
            continue
        m_tsz, = struct.unpack("<I", m_blob[4:8])
        src_masters = [sb.rstrip(b"\x00").decode("utf-8", "ignore")
                       for st, sb, _ in _iter_subs_raw(m_blob[24:24 + m_tsz]) if st == b"MAST"]
        src_masters.append(m_plug)

        target_low_ids = {int(wt["weap_fid"], 16) & 0x00FFFFFF: wt for wt in w_list}
        off = 24 + m_tsz
        while off + 24 <= len(m_blob):
            rt = m_blob[off:off+4]
            rsz, = struct.unpack("<I", m_blob[off+4:off+8])
            if rt == b"GRUP":
                off += 24
                continue
            rflags, raw_fid = struct.unpack("<II", m_blob[off+8:off+16])
            low_id = raw_fid & 0x00FFFFFF
            if rt == b"WEAP" and low_id in target_low_ids:
                dst_fid = _remap_fid(raw_fid, src_masters, existing_masters)
                if dst_fid in existing_weaps:
                    eb = existing_weaps[dst_fid]
                    r_body = eb[24:]
                else:
                    r_body = m_blob[off+24:off+24+rsz]
                    if rflags & 0x00040000:
                        r_body = zlib.decompress(r_body[4:])
                        rflags &= ~0x00040000

                rebuilt = bytearray()
                has_obts = False
                for st, sb, is_big in _iter_subs_raw(r_body):
                    if st == b"OBTS" and len(sb) >= 18:
                        has_obts = True
                        obuf = _remap_obts_blob(sb, src_masters, existing_masters) if dst_fid not in existing_weaps else bytearray(sb)
                        att_cnt, = struct.unpack("<I", obuf[0:4])
                        existing_pairs = set()
                        kw_cnt = obuf[15]
                        apos = 16 + kw_cnt * 4 + 2
                        for _ in range(att_cnt):
                            if apos + 7 <= len(obuf):
                                ofid, oidx_b = struct.unpack("<IB", obuf[apos:apos+5])
                                existing_pairs.add((ofid, oidx_b))
                            apos += 7
                        appr_kws = set()
                        for ast, asb, _ in _iter_subs_raw(r_body):
                            if ast == b"APPR":
                                for kp in range(0, len(asb) - 3, 4):
                                    kraw, = struct.unpack("<I", asb[kp:kp+4])
                                    kidx = kraw >> 24
                                    kown = (src_masters[kidx] if kidx < len(src_masters) else src_masters[-1]).lower()
                                    appr_kws.add(f"{kown}|0x{kraw & 0x00FFFFFF:06X}")
                        for om in omods:
                            ap_str = (om.get("attach_point") or "").lower()
                            if appr_kws and ap_str not in appr_kws:
                                continue
                            om_fid = (addon_m_idx << 24) | (int(om["form_id"], 16) & 0x00FFFFFF)
                            if (om_fid, 0) not in existing_pairs:
                                obuf.extend(struct.pack("<IHB", om_fid, 0, 0))
                                att_cnt += 1
                                added_pairs += 1
                        obuf[0:4] = struct.pack("<I", att_cnt)
                        rebuilt.extend(b"OBTS" + struct.pack("<H", len(obuf)) + obuf)
                    elif st == b"APPR" and not is_big:
                        ap_buf = bytearray(sb)
                        for kp in range(0, len(ap_buf) - 3, 4):
                            kraw, = struct.unpack("<I", ap_buf[kp:kp+4])
                            ap_buf[kp:kp+4] = struct.pack("<I", _remap_fid(kraw, src_masters, existing_masters))
                        rebuilt.extend(b"APPR" + struct.pack("<H", len(ap_buf)) + ap_buf)
                    elif is_big:
                        rebuilt.extend(b"XXXX\x04\x00" + struct.pack("<I", len(sb)) + st + b"\x00\x00" + sb)
                    else:
                        rebuilt.extend(st + struct.pack("<H", len(sb)) + sb)

                if has_obts:
                    rec_hdr = b"WEAP" + struct.pack("<IIIIH", len(rebuilt), rflags & ~0x00040000, dst_fid, 0, 131) + b"\x00\x00"
                    existing_weaps[dst_fid] = rec_hdr + bytes(rebuilt)
            off += 24 + rsz

    if not existing_weaps:
        return 0

    weap_blob = b"".join(existing_weaps.values())
    weap_grup = b"GRUP" + struct.pack("<I", 24 + len(weap_blob)) + b"WEAP" + struct.pack("<III", 0, 0, 0) + weap_blob
    tes4_subs = bytearray(b"HEDR\x0C\x00" + struct.pack("<fII", 1.0, len(existing_weaps), 0x00000800))
    tes4_subs.extend(b"CNAM\x0C\x00RobCoWizard\x00")
    for dm in existing_masters:
        mb = dm.encode("utf-8") + b"\x00"
        tes4_subs.extend(b"MAST" + struct.pack("<H", len(mb)) + mb + b"DATA\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    tes4_hdr = b"TES4" + struct.pack("<IIIIH", len(tes4_subs), 0x00000200, 0, 0, 131) + b"\x00\x00"

    os.makedirs(os.path.dirname(esl_path), exist_ok=True)
    with open(esl_path, "wb") as f:
        f.write(bytes(tes4_hdr) + bytes(tes4_subs) + weap_grup)
    return added_pairs

def prune_missing_masters_from_esl(esl_path: str, active_plugins: set) -> int:
    """Remove missing/disabled masters and orphaned OBTS WEAP records from RobCo_AutoSubLists.esp."""
    if not os.path.isfile(esl_path):
        return 0
    active_low = {p.lower() for p in active_plugins} | {"fallout4.esm"}

    with open(esl_path, "rb") as f:
        blob = bytes(f.read())
    if len(blob) < 24 or blob[0:4] != b"TES4":
        return 0

    tes4_sz, = struct.unpack("<I", blob[4:8])
    tes4_body = blob[24:24 + tes4_sz]
    masters: List[str] = []
    other_subs = bytearray()
    p = 0
    while p + 6 <= len(tes4_body):
        st = tes4_body[p:p+4]
        ssz, = struct.unpack("<H", tes4_body[p+4:p+6])
        ch = tes4_body[p+6:p+6+ssz]
        p += 6 + ssz
        if st == b"MAST":
            masters.append(ch.rstrip(b"\x00").decode("utf-8", "ignore"))
        elif st == b"DATA" and masters:
            continue
        else:
            other_subs.extend(st + struct.pack("<H", ssz) + ch)

    if not any(m.lower() not in active_low for m in masters):
        return 0

    kept_masters = [m for m in masters if m.lower() in active_low]
    if not kept_masters:
        kept_masters = ["Fallout4.esm"]
    old_to_new = {
        i: kept_masters.index(m)
        for i, m in enumerate(masters) if m in kept_masters
    }

    kept_grups = bytearray()
    total_recs = 0
    pruned_weaps = 0
    off = 24 + tes4_sz
    while off + 24 <= len(blob):
        rt = blob[off:off+4]
        rsz, = struct.unpack("<I", blob[off+4:off+8])
        if rt != b"GRUP":
            off += 24 + rsz
            continue
        g_label = blob[off+8:off+12]
        g_end = min(off + rsz, len(blob))
        rpos = off + 24
        off = g_end
        if g_label != b"WEAP":
            kept_grups.extend(blob[rpos - 24:g_end])
            scan = rpos
            while scan + 24 <= g_end:
                sub_sz, = struct.unpack("<I", blob[scan+4:scan+8])
                total_recs += 1
                scan += 24 + sub_sz
            continue

        while rpos + 24 <= g_end:
            rec_sz, = struct.unpack("<I", blob[rpos+4:rpos+8])
            rec_flags, fid = struct.unpack("<II", blob[rpos+8:rpos+16])
            rec_extra = blob[rpos+16:rpos+24]
            rbody = bytearray(blob[rpos+24:rpos+24+rec_sz])
            rpos += 24 + rec_sz

            owner_idx = fid >> 24
            if owner_idx not in old_to_new:
                pruned_weaps += 1
                continue

            valid_obts = True
            sp = 0
            while sp + 6 <= len(rbody):
                st = bytes(rbody[sp:sp+4])
                ssz, = struct.unpack("<H", rbody[sp+4:sp+6])
                if st == b"OBTS" and ssz >= 18:
                    att_cnt, = struct.unpack("<I", rbody[sp+6:sp+10])
                    kw_cnt = rbody[sp+20]
                    apos = sp + 6 + 16 + kw_cnt * 4 + 2
                    for _ in range(att_cnt):
                        if apos + 7 <= sp + 6 + ssz:
                            ofid, = struct.unpack("<I", rbody[apos:apos+4])
                            oidx = ofid >> 24
                            if oidx not in old_to_new:
                                valid_obts = False
                                break
                            rbody[apos:apos+4] = struct.pack("<I", (old_to_new[oidx] << 24) | (ofid & 0x00FFFFFF))
                        apos += 7
                    if not valid_obts:
                        break
                sp += 6 + ssz

            if not valid_obts:
                pruned_weaps += 1
                continue

            new_fid = (old_to_new[owner_idx] << 24) | (fid & 0x00FFFFFF)
            rec_hdr = b"WEAP" + struct.pack("<II", len(rbody), rec_flags) + struct.pack("<I", new_fid) + rec_extra
            grup_hdr = b"GRUP" + struct.pack("<I", 24 + len(rec_hdr) + len(rbody)) + b"WEAP" + struct.pack("<III", 0, 0, 0)
            kept_grups.extend(grup_hdr + rec_hdr + rbody)
            total_recs += 1

    new_tes4_body = bytearray(other_subs)
    for dm in kept_masters:
        mb = dm.encode("utf-8") + b"\x00"
        new_tes4_body.extend(b"MAST" + struct.pack("<H", len(mb)) + mb + b"DATA\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    new_tes4_hdr = b"TES4" + struct.pack("<IIIIH", len(new_tes4_body), 0x00000200, 0, 0, 131) + b"\x00\x00"
    final_blob = bytearray(new_tes4_hdr) + new_tes4_body + kept_grups

    hedr_pos = final_blob.find(b"HEDR\x0C\x00")
    if hedr_pos != -1:
        final_blob[hedr_pos+10:hedr_pos+14] = struct.pack("<I", max(1, total_recs))

    with open(esl_path, "wb") as f:
        f.write(final_blob)
    return pruned_weaps + (len(masters) - len(kept_masters))
