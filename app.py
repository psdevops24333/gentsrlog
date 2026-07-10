import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import json
import io

def remove_duplicates(lst):
    # ฟังก์ชันตัดข้อมูลซ้ำ
    seen = set()
    res = []
    for d in lst:
        # ใช้ tuple เพื่อเช็กความซ้ำซ้อน (ละเว้น _raw_id ถัามี)
        check_dict = {k: v for k, v in d.items() if k != "_raw_id"}
        t = tuple(sorted(check_dict.items()))
        if t not in seen:
            seen.add(t)
            res.append(d)
    return res

def format_clock_speed(val):
    # แปลงหน่วย MHz เป็น GHz
    if not val or not str(val).isdigit(): return str(val)
    ghz = int(val) / 1000
    return f"{int(ghz)} GHz" if ghz.is_integer() else f"{ghz:.2f} GHz"

def parse_tsr_log(uploaded_file):
    sys_dict = {"Model": "-", "Service Tag": "-", "Hostname": "-", "IP iDRAC": "-"}
    cpus, rams, disks, ctrls, nics, fcs = [], [], [], [], [], []
    
    # ฟังก์ชันประมวลผลข้อมูลฮาร์ดแวร์แต่ละชิ้น
    def process_component(ad):
        identity = ad.get('INSTANCEID', ad.get('FQDD', ad.get('DEVICEID', ''))).upper()
        
        if 'SYSTEM' in identity or 'BOARD' in identity:
            if ad.get('MODEL'): sys_dict['Model'] = ad['MODEL']
            if ad.get('SERVICETAG'): sys_dict['Service Tag'] = ad['SERVICETAG']
            if ad.get('HOSTNAME'): sys_dict['Hostname'] = ad['HOSTNAME']
            
        elif 'IPV4' in identity or 'IDRAC' in identity:
            ip = ad.get('CURRENTIPADDRESS', ad.get('ADDRESS'))
            if ip and ip not in ['0.0.0.0', '::', '127.0.0.1']: sys_dict['IP iDRAC'] = ip
            
        # ดึง CPU แบบละเอียด (Cores, Threads, Clock, Cache)
        elif 'CPU' in identity:
            m = ad.get('MODEL', ad.get('DEVICEDESCRIPTION', ad.get('NAME', '')))
            if m:
                cur_clk = format_clock_speed(ad.get('CURRENTCLOCKSPEED', ''))
                max_clk = format_clock_speed(ad.get('MAXCLOCKSPEED', ''))
                clk_str = cur_clk if cur_clk else "-"
                if max_clk and max_clk != "-": clk_str += f" (max {max_clk})"
                
                cpus.append({
                    "_raw_id": identity,
                    "Model": m,
                    "Clock": clk_str,
                    "Cores": ad.get('NUMBEROFPROCESSORCORES', ad.get('CORECOUNT', '-')),
                    "Threads": ad.get('NUMBEROFENABLEDTHREADS', ad.get('THREADCOUNT', '-')),
                    "L1": ad.get('PRIMARYCACHESIZE', ad.get('L1CACHE', '-')),
                    "L2": ad.get('SECONDARYCACHESIZE', ad.get('L2CACHE', '-')),
                    "L3": ad.get('TERTIARYCACHESIZE', ad.get('L3CACHE', '-')),
                    "Microcode": ad.get('MICROCODE', ad.get('CHARACTERISTICS', '-'))
                })
                
        # ดึง RAM แบบละเอียด (แปลงเป็น GB + Serial Number + Manufacturer)
        elif 'DIMM' in identity or 'MEMORY' in identity:
            sz = ad.get('SIZE', ad.get('CAPACITY', ''))
            sp = ad.get('SPEED', ad.get('OPERATINGSPEED', '-'))
            slot = ad.get('DEVICEDESCRIPTION', ad.get('NAME', identity))
            sn = ad.get('SERIALNUMBER', '-')
            mfg = ad.get('MANUFACTURER', '-')
            pn = ad.get('PARTNUMBER', '-')
            
            if sz and str(sz) not in ['0', '0 MB', '0 Bytes', 'None', '-']:
                sz_str = str(sz).replace(" MB", "").replace("MB", "").strip()
                if sz_str.isdigit():
                    gb = int(sz_str) / 1024
                    sz_val = f"{int(gb)} GB" if gb.is_integer() else f"{gb:.2f} GB"
                else:
                    sz_val = str(sz)
                    
                rams.append({
                    "Slot": slot,
                    "Size": sz_val,
                    "Speed": sp,
                    "Manufacturer": mfg,
                    "Part Number": pn,
                    "Serial Number": sn
                })
                
        # ดึง Disk แบบละเอียด (Serial Number, Protocol)
        elif 'DISK' in identity or 'PHYSICALDISK' in identity:
            sz = ad.get('SIZE', ad.get('SIZEINBYTES', ad.get('CAPACITY')))
            md = ad.get('MEDIATYPE', '-')
            pr = ad.get('BUSPROTOCOL', '-')
            n = ad.get('NAME', ad.get('DEVICEDESCRIPTION', identity))
            sn = ad.get('SERIALNUMBER', '-')
            fw = ad.get('REVISION', '-')
            
            if sz and str(sz) not in ['0', '0 Bytes']:
                if str(sz).isdigit() and int(sz) > 1000000:
                    gb = int(sz) / (1024**3)
                    sz_str = f"{gb/1024:.2f} TB" if gb >= 1000 else f"{gb:.2f} GB"
                else:
                    sz_str = str(sz)
                    
                disks.append({
                    "Device": n,
                    "Size": sz_str,
                    "Media Type": md,
                    "Protocol": pr,
                    "Revision (FW)": fw,
                    "Serial Number": sn
                })
                
        # ดึง Controller (RAID)
        elif any(x in identity for x in ['RAID', 'AHCI', 'CONTROLLER']):
            p = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
            fw = ad.get('FIRMWAREVERSION', ad.get('REVISION', '-'))
            if p: ctrls.append({"Device Name": p, "Firmware": fw})
            
        # ดึง Network (NIC)
        elif 'NIC' in identity or 'ETHERNET' in identity:
            p = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
            mac = ad.get('CURRENTMACADDRESS', ad.get('MACADDRESS', '-'))
            if p: nics.append({"Device Name": p, "MAC Address": mac})
            
        # ดึง Fibre Channel
        elif 'FC' in identity or 'FIBRECHANNEL' in identity:
            p = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
            fw = ad.get('FIRMWAREVERSION', '-')
            if p: fcs.append({"Device Name": p, "Firmware": fw})

    # --- ส่วนหลักของการอ่านไฟล์ ZIP ---
    try:
        with zipfile.ZipFile(uploaded_file, 'r') as outer_z:
            all_files = outer_z.namelist()
            inner_zip_name = next((f for f in all_files if f.lower().endswith('.zip')), None)
            
            if inner_zip_name:
                inner_zip_bytes = io.BytesIO(outer_z.read(inner_zip_name))
                target_z = zipfile.ZipFile(inner_zip_bytes, 'r')
                target_files = target_z.namelist()
            else:
                target_z = outer_z
                target_files = all_files

            inventory_json_file = next((f for f in target_files if 'hardware_inventory.json' in f.lower() or 'hw_inventory.json' in f.lower()), None)
            xml_files_to_parse = [f for f in target_files if ('sysinfo_' in f.lower() and f.lower().endswith('.xml')) or 'inventory.xml' in f.lower() or 'hw_inventory.xml' in f.lower()]

            if inventory_json_file:
                json_data = json.loads(target_z.read(inventory_json_file).decode('utf-8', errors='ignore'))
                components = json_data.get("SystemInventory", json_data).get("Component", [])
                if isinstance(components, dict): components = [components]
                
                for comp in components:
                    attrs = comp.get("Attribute", [])
                    if isinstance(attrs, dict): attrs = [attrs]
                    ad = {a.get("@Name", a.get("Name")).upper(): a.get("#text", a.get("Value", a.get("text"))) for a in attrs if a.get("@Name", a.get("Name"))}
                    ad['FQDD'] = comp.get("@FQDD", comp.get("FQDD", ""))
                    process_component(ad)

            elif xml_files_to_parse:
                for fname in xml_files_to_parse:
                    try:
                        root = ET.fromstring(target_z.read(fname))
                        for elem in root.iter():
                            if '}' in elem.tag: elem.tag = elem.tag.split('}', 1)[1]
                        
                        for comp in root.iter():
                            ad = {}
                            for k, v in comp.attrib.items(): ad[k.upper()] = str(v).strip()
                            for child in comp:
                                tag = child.tag.upper()
                                name_attr = child.get('Name') or child.get('NAME')
                                if tag in ['PROPERTY', 'ATTRIBUTE'] and name_attr:
                                    key = name_attr.upper()
                                    val = next((sub.text.strip() for sub in child if sub.tag.upper() == 'VALUE' and sub.text), child.text.strip() if child.text else "")
                                    if val: ad[key] = val
                                elif child.text and child.text.strip(): ad[tag] = child.text.strip()
                            
                            ad['DEVICEID'] = comp.tag
                            process_component(ad)
                    except: pass

        # --- จัดระเบียบข้อมูลขั้นสุดท้าย ---
        system_info = [{"Attribute": k, "Value": v} for k, v in sys_dict.items()]
        
        # จัดเรียง CPU และใส่เลข Index
        cpus_clean = []
        for i, cpu in enumerate(sorted(remove_duplicates(cpus), key=lambda x: x.get('_raw_id', ''))):
            cpu.pop('_raw_id', None) # ลบ id ออกไม่ให้โชว์ในตาราง
            new_cpu = {"Index": str(i + 1)}
            new_cpu.update(cpu)
            cpus_clean.append(new_cpu)
            
        rams_clean = sorted(remove_duplicates(rams), key=lambda x: x.get('Slot', ''))
        disks_clean = sorted(remove_duplicates(disks), key=lambda x: x.get('Device', ''))
        
        return {
            "System Information": system_info,
            "Processors": cpus_clean,
            "Memory": rams_clean,
            "Physical Disks": disks_clean,
            "Controller Cards": remove_duplicates(ctrls),
            "Interface LAN": remove_duplicates(nics),
            "FC Channels": remove_duplicates(fcs)
        }
        
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผลไฟล์: {e}")
        return {}

def export_to_docx(parsed_data):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    
    doc = Document()
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run("TSR Log Hardware Summary")
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(26, 82, 118)
    
    for section_name, records in parsed_data.items():
        if not records: continue
        
        heading = doc.add_heading(section_name, level=2)
        heading.runs[0].font.color.rgb = RGBColor(26, 82, 118)
        
        headers = list(records[0].
