import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import json
import io

def parse_tsr_log(uploaded_file):
    hardware_data = {K: "-" for K in ["Model", "Serial Number (Service Tag)", "Hostname", "IP iDRAC", "CPU", "RAM", "Physical Disk", "Controller Card", "Interface LAN", "FC Channel"]}
    cpu_l, ram_l, disk_l, ctrl_l, nic_l, fc_l = [], [], [], [], [], []

    try:
        with zipfile.ZipFile(uploaded_file, 'r') as outer_z:
            inner_zip = next((f for f in outer_z.namelist() if f.lower().endswith('.zip')), None)
            z = zipfile.ZipFile(io.BytesIO(outer_z.read(inner_zip)), 'r') if inner_zip else outer_z
            files = z.namelist()

            with st.expander("🔍 ดูโครงสร้างไฟล์ภายใน TSR ZIP"):
                st.write(f"จำนวนไฟล์ทั้งหมด: {len(files)} ไฟล์")
                st.code("\n".join(files[:20]))

            json_f = next((f for f in files if 'hardware_inventory.json' in f.lower() or 'hw_inventory.json' in f.lower()), None)
            xml_files = [f for f in files if ('sysinfo_' in f.lower() and f.lower().endswith('.xml')) or 'inventory.xml' in f.lower() or 'hw_inventory.xml' in f.lower()]

            # --- 1. จัดการไฟล์แบบ JSON ---
            if json_f:
                st.info(f"📄 ประมวลผลไฟล์ข้อมูลแบบ JSON: `{json_f}`")
                data = json.loads(z.read(json_f).decode('utf-8', errors='ignore')).get("SystemInventory", {})
                comps = data.get("Component", [])
                if isinstance(comps, dict): comps = [comps]
                for c in comps:
                    fqdd = c.get("@FQDD", c.get("FQDD", ""))
                    attrs = c.get("Attribute", [])
                    if isinstance(attrs, dict): attrs = [attrs]
                    ad = {a.get("@Name", a.get("Name")): a.get("#text", a.get("Value", a.get("text"))) for a in attrs if a.get("@Name", a.get("Name"))}
                    
                    fqdd_u = fqdd.upper()
                    if "SYSTEM.BOARD" in fqdd_u:
                        if ad.get("Model"): hardware_data["Model"] = ad["Model"]
                        if ad.get("ServiceTag"): hardware_data["Serial Number (Service Tag)"] = ad["ServiceTag"]
                    elif "IDRAC.EMBEDDED" in fqdd_u and ad.get("HostName"): hardware_data["Hostname"] = ad["HostName"]
                    elif "IPV4" in fqdd_u and ad.get("Address") and ad["Address"] != "0.0.0.0": hardware_data["IP iDRAC"] = ad["Address"]
                    elif "CPU.SOCKET" in fqdd_u and ad.get("Model"):
                        info = ad["Model"]
                        if ad.get("NumberOfProcessorCores") and ad.get("NumberOfEnabledThreads"):
                            info += f" ({ad['NumberOfProcessorCores']} Cores / {ad['NumberOfEnabledThreads']} Threads)"
                        cpu_l.append(info)
                    elif "DIMM.SOCKET" in fqdd_u and ad.get("Size") not in ["0 MB", "0", None]:
                        ram_l.append(f"[{fqdd}] {ad['Size']} @ {ad.get('Speed', '')}")
                    elif ("DISK." in fqdd_u or "PHYSICALDISK." in fqdd_u) and ad.get("Size"):
                        sz = ad["Size"]
                        if str(sz).isdigit() and int(sz) > 1000000:
                            gb = int(sz) / (1024**3)
                            sz = f"{gb/1024:.2f} TB" if gb >= 1000 else f"{gb:.2f} GB"
                        disk_l.append(f"[{fqdd}] {sz} {ad.get('MediaType', '')} {ad.get('BusProtocol', '')}")
                    elif ("RAID." in fqdd_u or "AHCI." in fqdd_u) and ad.get("ProductName"): ctrl_l.append(ad["ProductName"])
                    elif "NIC." in fqdd_u and ad.get("ProductName"): nic_l.append(ad["ProductName"])
                    elif ("FC." in fqdd_u or "FIBRECHANNEL." in fqdd_u) and ad.get("ProductName"): fc_l.append(ad["ProductName"])

            # --- 2. จัดการไฟล์แบบ XML (DCIM Property/Value) ---
            elif xml_files:
                st.info(f"📄 ประมวลผลไฟล์ข้อมูลแบบ XML ทั้งหมด {len(xml_files)} ไฟล์...")
                for f in xml_files:
                    try:
                        root = ET.fromstring(z.read(f))
                        for elem in root.iter():
                            if '}' in elem.tag: elem.tag = elem.tag.split('}', 1)[1]
                        for comp in root.iter():
                            if len(comp) > 0:
                                ad = {}
                                for k, v in comp.attrib.items(): ad[k.upper()] = str(v).strip()
                                for child in comp:
                                    t = child.tag.split('}')[-1].upper()
                                    name_attr = child.get('Name') or child.get('NAME')
                                    if t in ['PROPERTY', 'ATTRIBUTE'] and name_attr:
                                        k = name_attr.upper()
                                        val = next((sub.text.strip() for sub in child if sub.tag.split('}')[-1].upper() == 'VALUE' and sub.text), child.text.strip() if child.text else "")
                                        if val: ad[k] = val
                                    elif child.text and child.text.strip(): ad[t] = child.text.strip()
                                
                                identity = ad.get('INSTANCEID', ad.get('FQDD', ad.get('DEVICEID', comp.tag.upper()))).upper()
                                if identity not in ['PROPERTY', 'VALUE', 'ATTRIBUTE']:
                                    if 'SYSTEM' in identity or 'BOARD' in identity or 'DCIM_SYSTEMVIEW' in identity:
                                        if ad.get('MODEL'): hardware_data['Model'] = ad['MODEL']
                                        if ad.get('SERVICETAG'): hardware_data['Serial Number (Service Tag)'] = ad['SERVICETAG']
                                        if ad.get('HOSTNAME'): hardware_data['Hostname'] = ad['HOSTNAME']
                                    elif 'IPV4' in identity or 'IDRAC' in identity:
                                        ip = ad.get('CURRENTIPADDRESS', ad.get('ADDRESS'))
                                        if ip and ip not in ['0.0.0.0', '::', '127.0.0.1']: hardware_data['IP iDRAC'] = ip
                                    elif 'CPU' in identity:
                                        m = ad.get('MODEL', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
                                        c, th = ad.get('NUMBEROFPROCESSORCORES', ad.get('CORECOUNT', '')), ad.get('NUMBEROFENABLEDTHREADS', ad.get('THREADCOUNT', ''))
                                        if m: cpu_l.append(f"{m} ({c} Cores / {th} Threads)" if c and th else m)
                                    elif 'DIMM' in identity or 'MEMORY' in identity:
                                        sz, sp = ad.get('SIZE', ad.get('CAPACITY')), ad.get('SPEED', ad.get('OPERATINGSPEED', ''))
                                        slot = ad.get('DEVICEDESCRIPTION', ad.get('NAME', ''))
                                        if sz and str(sz) not in ['0', '0 MB', '0 Bytes', 'None', '-']:
                                            ram_l.append(f"[{slot}] {sz} MB @ {sp}" if str(sz).isdigit() else f"[{slot}] {sz} @ {sp}")
                                    elif 'DISK' in identity or 'PHYSICALDISK' in identity:
                                        sz, md, pr = ad.get('SIZE', ad.get('SIZEINBYTES', ad.get('CAPACITY'))), ad.get('MEDIATYPE', ''), ad.get('BUSPROTOCOL', '')
                                        n = ad.get('NAME', ad.get('DEVICEDESCRIPTION', ''))
                                        if sz and str(sz) not in ['0', '0 Bytes']:
                                            if str(sz).isdigit() and int(sz) > 1000000:
                                                gb = int(sz) / (1024**3)
                                                sz = f"{gb/1024:.2f} TB" if gb >= 1000 else f"{gb:.2f} GB"
                                            disk_l.append(f"[{n}] {sz} {md} {pr}".strip())
                                    elif any(x in identity for x in ['RAID', 'AHCI', 'CONTROLLER']):
                                        p = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
                                        if p: ctrl_l.append(p)
                                    elif 'NIC' in identity or 'ETHERNET' in identity:
                                        p = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
                                        if p: nic_l.append(p)
                                    elif 'FC' in identity or 'FIBRECHANNEL' in identity:
                                        p = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
                                        if p: fc_l.append(p)
                    except: pass

        if cpu_l: hardware_data['CPU'] = "\n".join(list(set(cpu_l)))
        if ram_l: hardware_data['RAM'] = "\n".join(ram_l)
        if disk_l: hardware_data['Physical Disk'] = "\n".join(disk_l)
        if ctrl_l: hardware_data['Controller Card'] = "\n".join(list(set(ctrl_l)))
        if nic_l: hardware_data['Interface LAN'] = "\n".join(list(set(nic_l)))
        if fc_l: hardware_data['FC Channel'] = "\n".join(list(set(fc_l)))
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผลไฟล์ ZIP: {e}")
    return hardware_data

def export_to_docx(data):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc = Document()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Lifecycle Log Summary Inventory")
    r.font.size, r.font.bold, r.font.color.rgb = Pt(18), True, RGBColor(26, 82, 118)
    
    table = doc.add_table(rows=1, cols=2)
    table.style = 'Table Grid'
    hdr = table.rows[0].cells
    hdr[0].text, hdr[1].text = 'Hardware Component', 'Details / Value'
    for cell in hdr:
        cell.paragraphs[0].runs[0].font.bold = True
        cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear'), shd.set(qn('w:color'), 'auto'), shd.set(qn('w:fill'), "1A5276")
