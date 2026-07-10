import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import json
import io

# --- ฟังก์ชันแปลงขนาดข้อมูลให้อ่านง่าย ---
def format_size(size_raw):
    if not size_raw or size_raw in ['0', '0 Bytes', '-', 'None']: return "-"
    size_str = str(size_raw).strip().upper()
    if size_str.replace('.', '').isdigit():
        val = float(size_str)
        if val > 1073741824: return f"{val / (1024**3):.2f} GB"
        if val > 1048576: return f"{val / (1024**2):.2f} MB"
        return f"{int(val)} Bytes"
    return size_str

# --- ฟังก์ชันหลัก ---
def parse_tsr_log(uploaded_file):
    components_extracted = []
    
    try:
        # 1. แตกไฟล์ ZIP
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

            json_file = next((f for f in target_files if 'hardware_inventory.json' in f.lower() or 'hw_inventory.json' in f.lower()), None)
            xml_files = [f for f in target_files if ('sysinfo_' in f.lower() and f.lower().endswith('.xml')) or 'inventory.xml' in f.lower() or 'hw_inventory.xml' in f.lower()]

            # 2. กวาดข้อมูลดิบ (JSON / XML) ทั้งหมดเก็บเป็น List of Dicts
            if json_file:
                json_data = json.loads(target_z.read(json_file).decode('utf-8', errors='ignore'))
                comps = json_data.get("SystemInventory", json_data).get("Component", [])
                if isinstance(comps, dict): comps = [comps]
                for c in comps:
                    attrs = c.get("Attribute", [])
                    if isinstance(attrs, dict): attrs = [attrs]
                    ad = {a.get("@Name", a.get("Name")).upper(): str(a.get("#text", a.get("Value", a.get("text")))).strip() for a in attrs if a.get("@Name", a.get("Name"))}
                    ad["_IDENTITY_"] = c.get("@FQDD", c.get("FQDD", "")).upper()
                    components_extracted.append(ad)

            elif xml_files:
                for fname in xml_files:
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
                            ad["_IDENTITY_"] = ad.get('INSTANCEID', ad.get('FQDD', ad.get('DEVICEID', comp.tag))).upper()
                            if ad["_IDENTITY_"] not in ['PROPERTY', 'VALUE', 'ATTRIBUTE']:
                                components_extracted.append(ad)
                    except: pass

        # 3. จัดกลุ่มและสร้างคอลัมน์ให้เหมือน HTML Report
        sys_info, cpus, rams, disks, ctrls, nics, fcs = {}, [], [], [], [], [], []
        
        for ad in components_extracted:
            identity = ad.get("_IDENTITY_", "")
            
            if 'SYSTEM' in identity or 'BOARD' in identity:
                if ad.get('MODEL'): sys_info['Model'] = ad['MODEL']
                if ad.get('SERVICETAG'): sys_info['Service Tag'] = ad['SERVICETAG']
                if ad.get('HOSTNAME'): sys_info['Hostname'] = ad['HOSTNAME']
            elif 'IPV4' in identity or 'IDRAC' in identity:
                ip = ad.get('CURRENTIPADDRESS', ad.get('ADDRESS'))
                if ip and ip not in ['0.0.0.0', '::', '127.0.0.1']: sys_info['IP iDRAC'] = ip
                
            elif 'CPU' in identity:
                model = ad.get('MODEL', ad.get('DEVICEDESCRIPTION', ad.get('NAME', '-')))
                clock = f"{ad.get('CURRENTCLOCKSPEED', '-')} (max {ad.get('MAXCLOCKSPEED', '-')})"
                cores = ad.get('NUMBEROFPROCESSORCORES', ad.get('CORECOUNT', '-'))
                threads = ad.get('NUMBEROFENABLEDTHREADS', ad.get('THREADCOUNT', '-'))
                l1 = ad.get('PRIMARYCACHE', ad.get('L1CACHE', '-'))
                l2 = ad.get('SECONDARYCACHE', ad.get('L2CACHE', '-'))
                l3 = ad.get('TERTIARYCACHE', ad.get('L3CACHE', '-'))
                microcode = ad.get('MICROCODEVERSION', ad.get('MICROCODE', '-'))
                
                if model != '-':
                    cpus.append({"Model": model, "Clock": clock, "Cores": cores, "Threads": threads, "L1": l1, "L2": l2, "L3": l3, "Microcode": microcode})
                    
            elif 'DIMM' in identity or 'MEMORY' in identity:
                slot = ad.get('DEVICEDESCRIPTION', ad.get('NAME', identity.split(':')[-1]))
                sz = format_size(ad.get('SIZE', ad.get('CAPACITY', '-')))
                sp = ad.get('SPEED', ad.get('OPERATINGSPEED', '-'))
                mfg = ad.get('MANUFACTURER', '-')
                pn = ad.get('PARTNUMBER', '-')
                sn = ad.get('SERIALNUMBER', '-')
                
                if sz != '-':
                    rams.append({"Slot": slot, "Capacity": sz, "Speed": sp, "Manufacturer": mfg, "Part Number": pn, "Serial Number": sn})
                    
            elif 'DISK' in identity or 'PHYSICALDISK' in identity:
                name = ad.get('NAME', ad.get('DEVICEDESCRIPTION', identity.split(':')[-1]))
                state = ad.get('STATE', ad.get('RAIDSTATUS', '-'))
                sz = format_size(ad.get('SIZE', ad.get('SIZEINBYTES', ad.get('CAPACITY', '-'))))
                media = ad.get('MEDIATYPE', '-')
                proto = ad.get('BUSPROTOCOL', '-')
                vend = ad.get('MANUFACTURER', ad.get('VENDORID', '-'))
                pid = ad.get('PRODUCTID', '-')
                
                if sz != '-':
                    disks.append({"Name": name, "State": state, "Capacity": sz, "Media Type": media, "Protocol": proto, "Vendor": vend, "Product ID": pid})
                    
            elif any(x in identity for x in ['RAID', 'AHCI', 'CONTROLLER']):
                name = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME', '-')))
                fw = ad.get('FIRMWAREVERSION', '-')
                drv = ad.get('DRIVERVERSION', '-')
                if name != '-' and 'USB' not in name.upper():
                    ctrls.append({"Device": name, "Firmware": fw, "Driver": drv})
                    
            elif 'NIC' in identity or 'ETHERNET' in identity:
                name = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME', '-')))
                mac = ad.get('CURRENTMACADDRESS', ad.get('MACADDRESS', '-'))
                link = ad.get('LINKSTATUS', '-')
                if name != '-':
                    nics.append({"Device": name, "MAC Address": mac, "Link Status": link})

        # ฟังก์ชันเคลียร์ค่าซ้ำและเติม Index
        def finalize_table(data_list):
            seen = set()
            res = []
            for d in data_list:
                t = tuple(d.items())
                if t not in seen:
                    seen.add(t)
                    res.append(d)
            # เติม Index
            for i, d in enumerate(res, 1):
                new_d = {"Index": i}
                new_d.update(d)
                res[i-1] = new_d
            return res

        return {
            "System Information": [{"Attribute": k, "Value": v} for k, v in sys_dict.items()],
            "Processors": finalize_table(cpus),
            "Memory": finalize_table(rams),
            "Physical Disks": finalize_table(disks),
            "Controller Cards": finalize_table(ctrls),
            "Network Interfaces": finalize_table(nics)
        }
        
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")
        return {}

# --- ฟังก์ชัน Export เป็นไฟล์ Word ---
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
        
        headers = list(records[0].keys())
        table = doc.add_table(rows=1, cols=len(headers))
        table.style = 'Table Grid'
        hdr_cells = table.rows[0].cells
        
        for i, h in enumerate(headers):
            hdr_cells[i].text = str(h)
            hdr_cells[i].paragraphs[0].runs[0].font.bold = True
            hdr_cells[i].paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
            tcPr = hdr_cells[i]._tc.get_or_add_tcPr()
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), "1A5276")
            tcPr.append(shd)
            
        for rec in records:
            row_cells = table.add_row().cells
            for i, h in enumerate(headers):
                row_cells[i].text = str(rec.get(h, ""))
        doc.add_paragraph() 
        
    docx_buffer = io.BytesIO()
    doc.save(docx_buffer)
    docx_buffer.seek(0)
    return docx_buffer

# --- UI หลัก ---
st.set_page_config(page_title="TSR Log Hardware Extractor", page_icon="🖥️", layout="wide")
st.title("🖥️ TSR Log Hardware Extractor")
st.subheader("ระบบแสดงผลสเปกเครื่องเชิงลึก (เทียบเท่า Dell HTML Report)")

uploaded_file = st.file_uploader("เลือกไฟล์ TSR Log (.zip)", type=["zip"])

if uploaded_file is not None:
    with st.spinner("กำลังเจาะลึกข้อมูล Attributes ทั้งหมด..."):
        parsed_data = parse_tsr_log(uploaded_file)
    
    if parsed_data:
        for section, records in parsed_data.items():
            if records:
                st.markdown(f"#### 🔹 {section}")
                # แสดงผลแบบตารางที่ซ่อน Index ด้านหน้าออก เพื่อให้คอลัมน์ "Index" ของเราเด่นขึ้น
                st.dataframe(records, hide_index=True, use_container_width=True)
        
        st.write("---")
        if st.button("🔄 ส่งออกรายงานทั้งหมดเป็นไฟล์ Word (.docx)"):
            try:
                docx_file = export_to_docx(parsed_data)
                service_tag = next((item['Value'] for item in parsed_data.get("System Information", []) if item['Attribute'] == "Service Tag"), "Unknown")
                st.download_button(
                    label="📥 ดาวน์โหลดไฟล์ Word (.docx)",
                    data=docx_file,
                    file_name=f"Hardware_Summary_{service_tag}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
            except Exception as e:
                st.error(f"ไม่สามารถสร้างไฟล์ Word ได้: {e}")

# --- สิ้นสุดไฟล์ (เลื่อนดูให้แน่ใจว่าเห็นบรรทัดนี้นะครับ) ---
