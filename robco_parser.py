import os
import re
import struct
import zlib


def find_already_patched_plugins(mods_dir: str, active_mods: set = None) -> set:
    """Returns a lowercase set of plugin filenames already referenced in any active RobCo leveledList INI."""
    patched = set()
    if not os.path.isdir(mods_dir):
        return patched

    pattern = re.compile(r"addToLLs=([^|~:\r\n]+\.(?:esm|esp|esl))\|", re.IGNORECASE)
    folders = active_mods if active_mods is not None else os.listdir(mods_dir)
    for mod_folder in folders:
        ll_dir = os.path.join(mods_dir, mod_folder, "F4SE", "Plugins", "RobCo_Patcher", "leveledList")
        if not os.path.isdir(ll_dir):
            continue
        for fname in os.listdir(ll_dir):
            if not fname.lower().endswith(".ini"):
                continue
            fpath = os.path.join(ll_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        s = line.strip()
                        if not s or s.startswith(";"):
                            continue
                        for m in pattern.finditer(s):
                            patched.add(m.group(1).lower())
            except Exception:
                continue
    return patched


def _iter_subrecords(body: bytes):
    pos = 0
    length = len(body)
    while pos + 6 <= length:
        sub_type = body[pos:pos + 4]
        sub_len = struct.unpack("<H", body[pos + 4:pos + 6])[0]
        pos += 6
        if pos + sub_len > length:
            break
        yield sub_type, body[pos:pos + sub_len]
        pos += sub_len


def parse_plugin(filepath: str) -> dict:
    """Parses a Fallout 4 .esp/.esl/.esm file, separating new mod records from vanilla overrides."""
    plugin_name = os.path.basename(filepath)
    empty = {"edits_vanilla_npcs": False,
        "plugin_name": plugin_name,
        "is_esl": False,
        "has_script_injector": False,
        "has_unpatched_records": False,
        "vanilla_ll_overrides": [],
        "lvlo_levels": [],
        "root_lvli": [],
        "masters": [],
        "weap_families": [],
        "armo_list": [],
        "npc_list": [],
        "omod_list": [],
        "lvli_list": [],
        "is_attachment_addon": False,
    }
    if not os.path.isfile(filepath):
        return empty

    with open(filepath, "rb") as f:
        data = f.read()

    if len(data) < 24 or data[0:4] != b"TES4":
        return empty

    tes4_size, tes4_flags = struct.unpack("<II", data[4:12])
    is_esl = bool(tes4_flags & 0x00000200) or filepath.lower().endswith(".esl")

    masters = []
    for stype, chunk in _iter_subrecords(data[24:24 + tes4_size]):
        if stype == b"MAST":
            masters.append(chunk.rstrip(b"\x00").decode("utf-8", errors="ignore"))
    mast_count = len(masters)

    raw_weap = {}
    raw_armo = {}
    raw_npc = {}
    raw_lvli = {}
    kywd_map = {}
    omod_recs = []
    has_script_injector = False
    vanilla_ll_overrides = set()
    lvlo_levels = set()
    edits_vanilla_npcs = False
    new_wrld_count = 0
    new_cell_count = 0
    total_cell_edits = 0

    def mask_fid(fid: int) -> str:
        masked = (fid & 0x00000FFF) if is_esl else (fid & 0x00FFFFFF)
        return f"0x{masked:06X}"

    def walk(offset: int, end: int):
        nonlocal has_script_injector, edits_vanilla_npcs, new_wrld_count, new_cell_count, total_cell_edits
        while offset + 24 <= end:
            rec_type = data[offset:offset + 4]
            rec_size = struct.unpack("<I", data[offset + 4:offset + 8])[0]

            if rec_type == b"GRUP":
                grup_end = min(offset + rec_size, end)
                walk(offset + 24, grup_end)
                offset = grup_end
                continue

            rec_flags, form_id = struct.unpack("<II", data[offset + 8:offset + 16])
            body_start = offset + 24
            body_end = min(body_start + rec_size, end)
            offset = body_end

            tag = rec_type.decode("ascii", errors="ignore")
            if tag == "CELL":
                total_cell_edits += 1
            if tag == "KYWD":
                kb = data[body_start:body_end]
                if (rec_flags & 0x00040000) and len(kb) >= 4:
                    try: kb = zlib.decompress(kb[4:])
                    except Exception: kb = b""
                for st, ch in _iter_subrecords(kb):
                    if st == b"EDID":
                        kywd_map[form_id & 0x00FFFFFF] = ch.rstrip(b"\x00").decode("utf-8", "ignore").lower()
                        break
                continue
            is_override = (form_id >> 24) < mast_count

            if is_override:
                if tag == "NPC_" and (form_id >> 24) == 0:
                    edits_vanilla_npcs = True
                if tag in ("LVLI", "LVLN") and (form_id >> 24) == 0:
                    vanilla_ll_overrides.add(f"Fallout4.esm|0x{form_id & 0x00FFFFFF:06X}")
                    body = data[body_start:body_end]
                    if (rec_flags & 0x00040000) and len(body) >= 4:
                        try:
                            body = zlib.decompress(body[4:])
                        except Exception:
                            continue
                    for stype, chunk in _iter_subrecords(body):
                        if stype == b"LVLO" and len(chunk) >= 8:
                            lvl, ref_fid = struct.unpack("<HxxI", chunk[0:8])
                            if (ref_fid >> 24) >= mast_count and lvl > 0:
                                lvlo_levels.add(lvl)
                continue
            if tag == "WRLD":
                new_wrld_count += 1
                continue
            if tag == "CELL":
                new_cell_count += 1
                continue

            if tag not in ("WEAP", "ARMO", "NPC_", "LVLI", "LVLN", "QUST", "OMOD", "KYWD"):
                continue

            body = data[body_start:body_end]
            if (rec_flags & 0x00040000) and len(body) >= 4:
                try:
                    body = zlib.decompress(body[4:])
                except Exception:
                    continue

            edid = ""
            full = ""
            obte = 0
            has_eitm = False
            stat_val = 0
            weap_weight = 0.0
            mag_cap = 0
            has_stock_slot = False
            kw_signals = []
            anim_signal = ""
            weap_class = ""
            lvlo_refs = []
            attach_pt = ""
            mnam_fids = []

            for stype, chunk in _iter_subrecords(body):
                if stype == b"EDID":
                    edid = chunk.rstrip(b"\x00").decode("utf-8", errors="ignore")
                elif stype == b"FULL" and len(chunk) > 1:
                    full = chunk.rstrip(b"\x00").decode("utf-8", errors="ignore")
                elif stype == b"OBTE" and len(chunk) >= 4:
                    obte = struct.unpack("<I", chunk[0:4])[0]
                elif stype == b"EITM":
                    has_eitm = True
                elif stype == b"DATA" and tag == "WEAP" and len(chunk) >= 8:
                    _, weap_weight = struct.unpack("<If", chunk[0:8])
                elif stype == b"APPR" and tag == "WEAP":
                    for off in range(0, len(chunk) - 3, 4):
                        af = int.from_bytes(chunk[off:off+4], "little")
                        if (af >> 24) == 0 and (af & 0x00FFFFFF) == 0x0005E5B5:
                            has_stock_slot = True
                elif stype == b"DATA" and tag == "WEAP" and len(chunk) >= 8:
                    _, weap_weight = struct.unpack("<If", chunk[0:8])
                elif stype == b"APPR" and tag == "WEAP":
                    for off in range(0, len(chunk) - 3, 4):
                        af = int.from_bytes(chunk[off:off+4], "little")
                        if (af >> 24) == 0 and (af & 0x00FFFFFF) == 0x0005E5B5:
                            has_stock_slot = True
                elif stype == b"DNAM":
                    if tag == "WEAP" and len(chunk) >= 100:
                        anim_off = {136: 85, 144: 89, 148: 93, 160: 97}.get(len(chunk), 85)
                        anim_type = int.from_bytes(chunk[anim_off:anim_off+1], "little")
                        w_flags = int.from_bytes(chunk[anim_off-13:anim_off-9], "little")
                        mag_cap = int.from_bytes(chunk[anim_off-31:anim_off-29], "little")
                        if anim_type in (0, 1, 2):
                            kw_signals.append("melee")
                        elif anim_type == 3:
                            kw_signals.append("pistol")
                        elif anim_type == 5:
                            kw_signals.append("heavy")
                        elif anim_type == 4:
                            kw_signals.append("auto_rifle") if (w_flags & 0x00008000) else "rifle"
                    elif tag == "ARMO" and len(chunk) >= 4:
                        stat_val = int.from_bytes(chunk[0:4], "little")
                elif stype == b"KWDA" and tag == "WEAP":
                    for off in range(0, len(chunk) - 3, 4):
                        kf = int.from_bytes(chunk[off:off+4], "little")
                        if (kf >> 24) == 0:
                            low_k = kf & 0x00FFFFFF
                            if low_k == 0x0004A0A3:
                                kw_signals.append("heavy")
                            elif low_k == 0x0004A0A5 and weap_class != "heavy":
                                kw_signals.append("sniper")
                            elif low_k == 0x0004A0A2 and weap_class not in ("heavy", "sniper"):
                                kw_signals.append("auto_rifle")
                            elif low_k in (0x0004A0A1, 0x0004A0A4) and not weap_class:
                                kw_signals.append("rifle")
                            elif low_k == 0x0004A0A0 and not weap_class:
                                kw_signals.append("pistol")
                            elif low_k in (0x0005240E, 0x0004A0A6, 0x0004A0A7) and not weap_class:
                                kw_signals.append("melee")
                        k_edid = kywd_map.get(kf & 0x00FFFFFF, "")
                        if k_edid and not weap_class:
                            if any(x in k_edid for x in ("heavy", "minigun", "gatling", "launcher")):
                                kw_signals.append("heavy")
                            elif "sniper" in k_edid:
                                kw_signals.append("sniper")
                            elif any(x in k_edid for x in ("rifle", "submachine", "smg", "shotgun", "carbine", "auto")):
                                kw_signals.append("auto_rifle")
                            elif any(x in k_edid for x in ("pistol", "revolver", "1911", "luger", "handgun")):
                                kw_signals.append("pistol")
                            elif "melee" in k_edid:
                                kw_signals.append("melee")
                elif stype == b"LVLO" and len(chunk) >= 8:
                    lvl, ref_fid = struct.unpack("<HxxI", chunk[0:8])
                    if lvl > 0:
                        lvlo_levels.add(lvl)
                    if (ref_fid >> 24) >= mast_count:
                        lvlo_refs.append(mask_fid(ref_fid))
                elif tag == "OMOD" and stype == b"DATA" and len(chunk) >= 20:
                    ap_raw = struct.unpack("<I", chunk[16:20])[0]
                    if ap_raw:
                        m_idx = ap_raw >> 24
                        m_name = masters[m_idx] if m_idx < mast_count else plugin_name
                        ap_masked = (ap_raw & 0x00000FFF) if (m_name.lower().endswith(".esl") or (m_idx >= mast_count and is_esl)) else (ap_raw & 0x00FFFFFF)
                        attach_pt = f"{m_name}|0x{ap_masked:06X}"
                elif tag == "OMOD" and stype == b"MNAM":
                    for off in range(0, len(chunk) - 3, 4):
                        kf = int.from_bytes(chunk[off:off+4], "little")
                        if kf:
                            m_idx = kf >> 24
                            m_name = masters[m_idx] if m_idx < mast_count else plugin_name
                            kf_masked = (kf & 0x00000FFF) if (m_name.lower().endswith(".esl") or (m_idx >= mast_count and is_esl)) else (kf & 0x00FFFFFF)
                            mnam_fids.append(f"{m_name}|0x{kf_masked:06X}")

            if tag == "KYWD":
                kywd_map[form_id & 0x00FFFFFF] = edid.lower()
                continue

            if tag == "QUST":
                low = edid.lower()
                if "inject" in low or "leveledlist" in low or low.startswith("ll_"):
                    has_script_injector = True
                continue

            is_non_playable = bool(rec_flags & 0x00000004)
            fid_hex = mask_fid(form_id)

            if tag == "WEAP" and not is_non_playable:
                raw_weap[fid_hex] = {
                    "type": "WEAP",
                    "category": "WEAP",
                    "form_id": fid_hex,
                    "edid": edid,
                    "name": full or edid or fid_hex,
                    "templates": obte,
                    "is_unique": has_eitm or ("unique" in f"{edid} {full}".lower()),
                    "stat": stat_val,
                    "weight": weap_weight,
                    "mag_cap": mag_cap,
                    "has_stock_slot": has_stock_slot,
                    "kw_signals": kw_signals,
                    "weap_class": weap_class,
                }
            elif tag == "ARMO" and not is_non_playable and full:
                raw_armo[fid_hex] = {
                    "type": "ARMO",
                    "category": "ARMO",
                    "form_id": fid_hex,
                    "edid": edid,
                    "name": full,
                    "is_unique": has_eitm or ("unique" in f"{edid} {full}".lower()),
                    "stat": stat_val,
                }
            elif tag == "NPC_" and full and not edid.startswith(("MQ", "DLC")):
                raw_npc[fid_hex] = {
                    "type": "NPC_",
                    "category": "NPC_",
                    "form_id": fid_hex,
                    "edid": edid,
                    "name": full,
                    "is_unique": False,
                    "stat": 10,
                }
            elif tag == "LVLI":
                raw_lvli[fid_hex] = {"type": "LVLI", "form_id": fid_hex, "edid": edid, "refs": lvlo_refs}
            elif tag == "OMOD":
                omod_recs.append({
                    "type": "OMOD",
                    "form_id": fid_hex,
                    "edid": edid,
                    "name": full or edid or fid_hex,
                    "attach_point": attach_pt,
                    "mnam": mnam_fids,
                })

    walk(24 + tes4_size, len(data))

    referenced_lvlis = set()
    for lv in raw_lvli.values():
        for r in lv["refs"]:
            if r in raw_lvli:
                referenced_lvlis.add(r)

    omod_fids = {o["form_id"] for o in omod_recs}

    def classify_lvli(fid: str, seen=None):
        seen = seen or set()
        if fid in seen or fid not in raw_lvli:
            return None
        seen.add(fid)
        for r in raw_lvli[fid]["refs"]:
            if r in raw_weap:
                return "WEAP"
            if r in raw_armo:
                return "ARMO"
            if r in omod_fids:
                return "OMOD_LIST"
            sub = classify_lvli(r, seen)
            if sub:
                return sub
        return None

    root_lvli = []
    for fid, lv in raw_lvli.items():
        if fid in referenced_lvlis:
            continue
        cat = classify_lvli(fid)
        if cat in ("WEAP", "ARMO"):
            root_lvli.append({
                "type": "LVLI",
                "category": cat,
                "form_id": fid,
                "edid": lv["edid"],
                "name": f"{lv['edid'] or fid} [Root LVLI - {len(lv['refs'])} entries]",
                "entry_count": len(lv["refs"]),
                "is_unique": False,
                "stat": 20,
            })

    omod_blob = " ".join(f"{o.get('edid', '')} {o.get('name', '')}" for o in omod_recs).lower()
    omod_auto = any(k in omod_blob for k in ("receiver_auto", "auto_receiver", "fullauto", "full_auto", "rapid"))
    omod_sniper = any(k in omod_blob for k in ("sniper", "longrange", "recon_scope"))
    omod_stock = any(k in omod_blob for k in ("stock", "handguard", "foregrip", "barrel_long"))
    for w in raw_weap.values():
        sc = {"melee": 0, "pistol": 0, "rifle": 0, "auto_rifle": 0, "sniper": 0, "heavy": 0}
        for s in w.get("kw_signals", []): sc[s] = sc.get(s, 0) + 3
        if w.get("has_stock_slot") or omod_stock: sc["rifle"] += 2
        if omod_auto: sc["auto_rifle"] += 2
        if omod_sniper: sc["sniper"] += 2
        if w.get("mag_cap", 0) >= 50: sc["heavy"] += 2; sc["auto_rifle"] += 1
        elif w.get("mag_cap", 0) >= 25: sc["auto_rifle"] += 1
        wt = w.get("weight", 0.0)
        if wt >= 18.0: sc["heavy"] += 2
        elif wt >= 6.0: sc["rifle"] += 1
        elif 0.0 < wt < 4.5: sc["pistol"] += 1
        best, val = max(sc.items(), key=lambda kv: kv)
        w["weap_class"] = best if val > 0 else ""

    omod_blob = " ".join(f"{o.get('edid', '')} {o.get('name', '')}" for o in omod_recs).lower()
    omod_auto = any(k in omod_blob for k in ("receiver_auto", "auto_receiver", "fullauto", "full_auto", "rapid"))
    omod_sniper = any(k in omod_blob for k in ("sniper", "longrange", "recon_scope"))
    omod_stock = any(k in omod_blob for k in ("stock", "handguard", "foregrip", "barrel_long"))
    for w in raw_weap.values():
        sc = {"melee": 0, "pistol": 0, "rifle": 0, "auto_rifle": 0, "sniper": 0, "heavy": 0}
        for s in w.get("kw_signals", []): sc[s] = sc.get(s, 0) + 3
        if w.get("has_stock_slot") or omod_stock: sc["rifle"] += 2
        if omod_auto: sc["auto_rifle"] += 2
        if omod_sniper: sc["sniper"] += 2
        if w.get("mag_cap", 0) >= 50: sc["heavy"] += 2; sc["auto_rifle"] += 1
        elif w.get("mag_cap", 0) >= 25: sc["auto_rifle"] += 1
        wt = w.get("weight", 0.0)
        if wt >= 18.0: sc["heavy"] += 2
        elif wt >= 6.0: sc["rifle"] += 1
        elif 0.0 < wt < 4.5: sc["pistol"] += 1
        best, val = max(sc.items(), key=lambda kv: kv)
        w["weap_class"] = best if val > 0 else ""

    omod_blob = " ".join(f"{o.get('edid', '')} {o.get('name', '')}" for o in omod_recs).lower()
    omod_auto = any(k in omod_blob for k in ("receiver_auto", "auto_receiver", "fullauto", "full_auto", "rapid"))
    omod_sniper = any(k in omod_blob for k in ("sniper", "longrange", "recon_scope"))
    omod_stock = any(k in omod_blob for k in ("stock", "handguard", "foregrip", "barrel_long"))
    for w in raw_weap.values():
        sc = {"melee": 0, "pistol": 0, "rifle": 0, "auto_rifle": 0, "sniper": 0, "heavy": 0}
        for s in w.get("kw_signals", []): sc[s] = sc.get(s, 0) + 3
        if w.get("has_stock_slot") or omod_stock: sc["rifle"] += 2
        if omod_auto: sc["auto_rifle"] += 2
        if omod_sniper: sc["sniper"] += 2
        if w.get("mag_cap", 0) >= 50: sc["heavy"] += 2; sc["auto_rifle"] += 1
        elif w.get("mag_cap", 0) >= 25: sc["auto_rifle"] += 1
        wt = w.get("weight", 0.0)
        if wt >= 18.0: sc["heavy"] += 2
        elif wt >= 6.0: sc["rifle"] += 1
        elif 0.0 < wt < 4.5: sc["pistol"] += 1
        best, val = max(sc.items(), key=lambda kv: kv)
        w["weap_class"] = best if val > 0 else ""

    families = {}
    for w in raw_weap.values():
        key = w["name"].strip().lower()
        families.setdefault(key, []).append(w)

    weap_families = []
    for members in families.values():
        members.sort(key=lambda x: (x["is_unique"], len(x["edid"])))
        rep = members[0]
        tmpl_note = f" [{rep['templates']} Templates]" if rep["templates"] > 1 else ""
        var_note = f" ({len(members)} variants)" if len(members) > 1 else ""
        weap_families.append({
            "type": "WEAP_FAMILY",
            "category": "WEAP",
            "form_id": rep["form_id"],
            "members": members,
            "edid": rep["edid"],
            "name": f"{rep['name']}{var_note}{tmpl_note}",
            "is_unique": all(m["is_unique"] for m in members),
            "stat": rep["stat"],
            "weap_class": rep.get("weap_class", ""),
        })

    armo_list = list(raw_armo.values())
    npc_list = list(raw_npc.values())
    lvli_list = [
        {"form_id": fid, "edid": lv["edid"], "category": classify_lvli(fid)}
        for fid, lv in raw_lvli.items()
    ]
    _framework_masters = {
        "fallout4.esm", "dlcrobot.esm", "dlcworkshop01.esm",
        "dlccoast.esm", "dlcworkshop02.esm", "dlcworkshop03.esm", "dlcnukaworld.esm",
        "munitions - an ammo expansion.esl", "munitions additional ammo redux.esl", "tacticalreload.esm", "metroweaponframework.esl",
    }
    low_plug = plugin_name.lower()
    is_sts_patch = any(k in low_plug for k in ("3dscopes", "sts", "see-through-scopes"))
    custom_masters = [
        m for m in masters
        if m.lower() not in _framework_masters and (is_sts_patch or not m.lower().startswith("cc"))
    ]
    is_attachment_addon = bool(
        custom_masters and len(omod_recs) >= 3
        and len(weap_families) <= 4 and not armo_list and not raw_npc
    )
    has_records = bool(root_lvli or weap_families or armo_list or npc_list or is_attachment_addon)

    return {
        "plugin_name": plugin_name,
        "is_esl": is_esl,
        "masters": masters,
        "has_script_injector": has_script_injector,
        "edits_vanilla_npcs": edits_vanilla_npcs,
        "has_unpatched_records": has_records,
        "vanilla_ll_overrides": sorted(vanilla_ll_overrides),
        "lvlo_levels": sorted(lvlo_levels),
        "root_lvli": root_lvli,
        "weap_families": weap_families,
        "armo_list": armo_list,
        "npc_list": npc_list,
        "omod_list": omod_recs,
        "lvli_list": lvli_list,
        "is_attachment_addon": is_attachment_addon,
        "new_wrld_count": new_wrld_count,
        "new_cell_count": new_cell_count,
        "total_cell_edits": total_cell_edits,
    }
