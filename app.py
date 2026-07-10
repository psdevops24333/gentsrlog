import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import json
import io

def remove_duplicates(lst):
    seen = set()
    res = []
    for d in lst:
        t = tuple(sorted(d.items()))
        if t not in seen:
            seen.add(t)
            res.append(d)
    return res

def parse_tsr_log(uploaded_file):
    sys_dict = {"Model": "-", "Service Tag": "-", "Hostname": "-", "IP iDRAC": "-"}
    cpus, rams, disks, ctrls, nics, fcs = [], [], [], [], [], []
    
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

            # --- จัดการ JSON ---
            if inventory_json_file:
                json_data = json.loads(target_z.read(inventory_json_file).decode('utf-8', errors='ignore'))
                components = json_data.get("SystemInventory", json_data).get("Component", [])
                if isinstance(components, dict): components = [components]
                
                for comp in components:
                    fqdd = comp.get("@FQDD", comp.get("FQDD", "")).upper()
                    attrs = comp.get("Attribute", [])
                    if isinstance(attrs, dict): attrs = [attrs]
                    ad = {a.get("@Name", a.get("Name")).upper(): a.get("#text", a.get("Value", a.get("text"))) for a in attrs if a.get("@Name", a.get("Name"))}

                    if "SYSTEM.BOARD" in fqdd:
                        if "MODEL" in ad: sys_dict["Model"] = ad["MODEL"]
                        if "SERVICETAG" in ad: sys_dict["Service Tag"] = ad["SERVICETAG"]
                    elif "IDRAC.EMBEDDED" in fqdd and "HOSTNAME" in ad: sys_dict["Hostname"] = ad["HOSTNAME"]
                    elif "IPV4" in fqdd and "ADDRESS" in ad and ad["ADDRESS"] != "0.0.0.0": sys_dict["IP iDRAC"] = ad["ADDRESS"]
                    
                    elif "CPU.SOCKET" in fqdd and "MODEL" in ad:
                        cpus.append({"Socket": fqdd, "Model": ad["MODEL"], "Cores": ad.get("NUMBEROFPROCESSORCORES", ""), "Threads": ad.get("NUMBEROFENABLEDTHREADS", "")})
                    elif "DIMM.SOCKET" in fqdd and ad.get("SIZE") not in ["0 MB", "0", None]:
                        rams.append({"Slot": fqdd, "Size": ad["SIZE"], "Speed": ad.get("SPEED", "")})
                    elif ("DISK." in fqdd or "PHYSICALDISK." in fqdd) and "SIZE" in ad:
                        sz = ad["SIZE"]
                        if str(sz).isdigit() and int(sz) > 1000000:
                            gb = int(sz) / (1024**3)
                            sz = f"{gb/1024:.2f} TB" if gb >= 1000 else f"{gb:.2f} GB"
                        disks.append({"Device": fqdd, "Size": sz, "Media Type": ad.get("MEDIATYPE", ""), "Protocol": ad.get("BUSPROTOCOL", "")})
                    elif ("RAID" in fqdd or "AHCI" in fqdd) and "PRODUCTNAME" in ad: ctrls.append({"Device Name": ad["PRODUCTNAME"]})
                    elif "NIC" in fqdd and "PRODUCTNAME" in ad: nics.append({"Device Name": ad["PRODUCTNAME"]})
                    elif "FC." in fqdd and "PRODUCTNAME" in ad: fcs.append({"Device Name": ad["PRODUCTNAME"]})

            # --- จัดการ XML ---
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
                            
                            identity = ad.get('INSTANCEID', ad.get('FQDD', ad.get('DEVICEID', comp.tag))).upper()

                            if 'SYSTEM' in identity or 'BOARD' in identity:
                                if ad.get('MODEL'): sys_dict['Model'] = ad['MODEL']
                                if ad.get('SERVICETAG'): sys_dict['Service Tag'] = ad['SERVICETAG']
                                if ad.get('HOSTNAME'): sys_dict['Hostname'] = ad['HOSTNAME']
                            elif 'IPV4' in identity or 'IDRAC' in identity:
                                ip = ad.get('CURRENTIPADDRESS', ad.get('ADDRESS'))
                                if ip and ip not in ['0.0.0.0', '::', '127.0.0.1']: sys_dict['IP iDRAC'] = ip
                            
                            elif 'CPU' in identity:
                                m = ad.get('MODEL', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
                                c = ad.get('NUMBEROFPROCESSORCORES', ad.get('CORECOUNT', ''))
                                th = ad.get('NUMBEROFENABLEDTHREADS', ad.get('THREADCOUNT', ''))
                                if m: cpus.append({"Model": m, "Cores": c, "Threads": th})
                            elif 'DIMM' in identity or 'MEMORY' in identity:
                                sz = ad.get('SIZE', ad.get('CAPACITY'))
                                sp = ad.get('SPEED', ad.get('OPERATINGSPEED', ''))
                                slot = ad.get('DEVICEDESCRIPTION', ad.get('NAME', identity))
                                if sz and str(sz) not in ['0', '0 MB', '0 Bytes', 'None', '-']:
                                    sz_str = f"{sz} MB" if str(sz).isdigit() else str(sz)
                                    rams.append({"Slot": slot, "Size": sz_str, "Speed": sp})
                            elif 'DISK' in identity or 'PHYSICALDISK' in identity:
                                sz = ad.get('SIZE', ad.get('SIZEINBYTES', ad.get('CAPACITY')))
                                md, pr = ad.get('MEDIATYPE', ''), ad.get('BUSPROTOCOL', '')
                                n = ad.get('NAME', ad.get('DEVICEDESCRIPTION', identity))
                                if sz and str(sz) not in ['0', '0 Bytes']:
                                    if str(sz).isdigit() and int(sz) > 1000000:
                                        gb = int(sz) / (1024**3)
                                        sz = f"{gb/1024:.2f} TB" if gb >= 1000 else f"{gb:.2f} GB"
                                    disks.append({"Device": n, "Size": sz, "Media Type": md, "Protocol": pr})
                            elif any(x in identity for x in ['RAID', 'AHCI', 'CONTROLLER']):
                                p = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
                                if p: ctrls.append({"Device Name": p})
                            elif 'NIC' in identity or 'ETHERNET' in identity:
                                p = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
                                if p: nics.append({"Device Name": p})
                            elif 'FC' in identity or 'FIBRECHANNEL' in identity:
                                p = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME')))
                                if p: fcs.append({"Device Name": p})
                    except: pass

        # จัดระเบียบและเรียงข้อมูล
        system_info = [{"Attribute": k, "Value": v} for k, v in sys_dict.items()]
        
        # จัดการการเรียงลำดับ Slot / ตัวอักษร
        rams_clean = sorted(remove_duplicates(rams), key=lambda x: x.get('Slot', ''))
        disks_clean = sorted(remove_duplicates(disks), key=lambda x: x.get('Device', ''))
        
        return {
            "System Information": system_info,
            "Processors": remove_duplicates(cpus),
            "Memory": rams_clean,
            "Physical Disks": disks_clean,
            "Controller Cards": remove_duplicates(ctrls),
            "Interface LAN": remove_duplicates(nics),
            "FC Channels": remove_duplicates(fcs)
        }
        
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")
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
        doc.add_paragraph() # เว้นบรรทัดหลังจบแต่ละตาราง
        
    docx_buffer = io.BytesIO()
    doc.save(docx_buffer)
    docx_buffer.seek(0)
    return docx_buffer

st.set_page_config(page_title="TSR Log Hardware Extractor", page_icon="🖥️", layout="wide")
st.title("🖥️ TSR Log Hardware Extractor")
st.subheader("ระบบแสดงผลแบบตารางแยกหมวดหมู่ (Hardware Summary Tables)")

uploaded_file = st.file_uploader("เลือกไฟล์ TSR Log (.zip)", type=["zip"])

if uploaded_file is not None:
    st.success("โหลดไฟล์สำเร็จ! กำลังสร้างตารางข้อมูล...")
    
    parsed_data = parse_tsr_log(uploaded_file)
    
    if parsed_data:
        # แสดงผลตารางแยกทีละหัวข้อบนหน้าเว็บ
        for section, records in parsed_data.items():
            if records:
                st.markdown(f"#### 🔹 {section}")
                st.table(records)
        
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
