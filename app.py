import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import json
import io

def parse_tsr_log(uploaded_file):
    hardware_data = {
        "Model": "-", "Serial Number (Service Tag)": "-", "Hostname": "-",
        "IP iDRAC": "-", "CPU": "-", "RAM": "-", "Physical Disk": "-",
        "Controller Card": "-", "Interface LAN": "-", "FC Channel": "-"
    }
    
    cpu_list, ram_list, disk_list, controller_list, nic_list, fc_list = [], [], [], [], [], []
    
    try:
        with zipfile.ZipFile(uploaded_file, 'r') as outer_z:
            all_files = outer_z.namelist()
            
            inner_zip_name = None
            for fname in all_files:
                if fname.lower().endswith('.zip'):
                    inner_zip_name = fname
                    break
            
            if inner_zip_name:
                inner_zip_bytes = io.BytesIO(outer_z.read(inner_zip_name))
                target_z = zipfile.ZipFile(inner_zip_bytes, 'r')
                target_files = target_z.namelist()
            else:
                target_z = outer_z
                target_files = all_files

            inventory_json_file = None
            xml_files_to_parse = []
            for fname in target_files:
                fname_lower = fname.lower()
                if 'hardware_inventory.json' in fname_lower or 'hw_inventory.json' in fname_lower:
                    inventory_json_file = fname
                if 'inventory.xml' in fname_lower or 'hw_inventory.xml' in fname_lower:
                    xml_files_to_parse.append(fname)
                if 'sysinfo_' in fname_lower and fname_lower.endswith('.xml'):
                    xml_files_to_parse.append(fname)

            # --- จัดการ JSON ---
            if inventory_json_file:
                json_data = json.loads(target_z.read(inventory_json_file).decode('utf-8', errors='ignore'))
                components = json_data.get("SystemInventory", json_data).get("Component", [])
                if isinstance(components, dict): components = [components]
                
                for comp in components:
                    fqdd = comp.get("@FQDD", comp.get("FQDD", "")).upper()
                    attrs = comp.get("Attribute", [])
                    if isinstance(attrs, dict): attrs = [attrs]
                    attr_dict = {a.get("@Name", a.get("Name")).upper(): a.get("#text", a.get("Value", a.get("text"))) for a in attrs if a.get("@Name", a.get("Name"))}

                    if "SYSTEM.BOARD" in fqdd:
                        if "MODEL" in attr_dict: hardware_data["Model"] = attr_dict["MODEL"]
                        if "SERVICETAG" in attr_dict: hardware_data["Serial Number (Service Tag)"] = attr_dict["SERVICETAG"]
                    elif "IDRAC.EMBEDDED" in fqdd and "HOSTNAME" in attr_dict:
                        hardware_data["Hostname"] = attr_dict["HOSTNAME"]
                    elif "IPV4" in fqdd and "ADDRESS" in attr_dict and attr_dict["ADDRESS"] != "0.0.0.0":
                        hardware_data["IP iDRAC"] = attr_dict["ADDRESS"]
                    elif "CPU.SOCKET" in fqdd and "MODEL" in attr_dict:
                        info = attr_dict["MODEL"]
                        cores = attr_dict.get("NUMBEROFPROCESSORCORES")
                        threads = attr_dict.get("NUMBEROFENABLEDTHREADS")
                        if cores and threads: info += f" ({cores} Cores / {threads} Threads)"
                        cpu_list.append(info)
                    elif "DIMM.SOCKET" in fqdd and attr_dict.get("SIZE") not in ["0 MB", "0", None]:
                        ram_list.append(f"[{fqdd}] {attr_dict['SIZE']} @ {attr_dict.get('SPEED', '')}")
                    elif ("DISK." in fqdd or "PHYSICALDISK." in fqdd) and "SIZE" in attr_dict:
                        sz = attr_dict["SIZE"]
                        if str(sz).isdigit() and int(sz) > 1000000:
                            gb = int(sz) / (1024**3)
                            sz = f"{gb/1024:.2f} TB" if gb >= 1000 else f"{gb:.2f} GB"
                        disk_list.append(f"[{fqdd}] {sz} {attr_dict.get('MEDIATYPE', '')} {attr_dict.get('BUSPROTOCOL', '')}".strip())
                    elif ("RAID" in fqdd or "AHCI" in fqdd) and "PRODUCTNAME" in attr_dict:
                        controller_list.append(attr_dict["PRODUCTNAME"])
                    elif "NIC" in fqdd and "PRODUCTNAME" in attr_dict:
                        nic_list.append(attr_dict["PRODUCTNAME"])
                    elif "FC." in fqdd and "PRODUCTNAME" in attr_dict:
                        fc_list.append(attr_dict["PRODUCTNAME"])

            # --- จัดการ XML ---
            elif xml_files_to_parse:
                for fname in xml_files_to_parse:
                    try:
                        root = ET.fromstring(target_z.read(fname))
                        for elem in root.iter():
                            if '}' in elem.tag: elem.tag = elem.tag.split('}', 1)[1]
                        
                        for comp in root.iter():
                            attr_dict = {}
                            for k, v in comp.attrib.items(): attr_dict[k.upper()] = str(v).strip()
                            for child in comp:
                                tag = child.tag.upper()
                                name_attr = child.get('Name') or child.get('NAME')
                                if tag in ['PROPERTY', 'ATTRIBUTE'] and name_attr:
                                    key = name_attr.upper()
                                    val = next((sub.text.strip() for sub in child if sub.tag.upper() == 'VALUE' and sub.text), child.text.strip() if child.text else "")
                                    if val: attr_dict[key] = val
                                elif child.text and child.text.strip():
                                    attr_dict[tag] = child.text.strip()
                            
                            identity = attr_dict.get('INSTANCEID', attr_dict.get('FQDD', attr_dict.get('DEVICEID', comp.tag))).upper()

                            if 'SYSTEM' in identity or 'BOARD' in identity:
                                if attr_dict.get('MODEL'): hardware_data['Model'] = attr_dict['MODEL']
                                if attr_dict.get('SERVICETAG'): hardware_data['Serial Number (Service Tag)'] = attr_dict['SERVICETAG']
                                if attr_dict.get('HOSTNAME'): hardware_data['Hostname'] = attr_dict['HOSTNAME']
                            elif 'IPV4' in identity or 'IDRAC' in identity:
                                ip = attr_dict.get('CURRENTIPADDRESS', attr_dict.get('ADDRESS'))
                                if ip and ip not in ['0.0.0.0', '::', '127.0.0.1']: hardware_data['IP iDRAC'] = ip
                            elif 'CPU' in identity:
                                m = attr_dict.get('MODEL', attr_dict.get('DEVICEDESCRIPTION', attr_dict.get('NAME')))
                                c, th = attr_dict.get('NUMBEROFPROCESSORCORES', attr_dict.get('CORECOUNT')), attr_dict.get('NUMBEROFENABLEDTHREADS', attr_dict.get('THREADCOUNT'))
                                if m: cpu_list.append(f"{m} ({c} Cores / {th} Threads)" if c and th else m)
                            elif 'DIMM' in identity or 'MEMORY' in identity:
                                sz = attr_dict.get('SIZE', attr_dict.get('CAPACITY'))
                                sp = attr_dict.get('SPEED', attr_dict.get('OPERATINGSPEED', ''))
                                slot = attr_dict.get('DEVICEDESCRIPTION', attr_dict.get('NAME', ''))
                                if sz and str(sz) not in ['0', '0 MB', '0 Bytes', 'None', '-']:
                                    ram_list.append(f"[{slot}] {sz} MB @ {sp}" if str(sz).isdigit() else f"[{slot}] {sz} @ {sp}")
                            elif 'DISK' in identity or 'PHYSICALDISK' in identity:
                                sz = attr_dict.get('SIZE', attr_dict.get('SIZEINBYTES', attr_dict.get('CAPACITY')))
                                md, pr = attr_dict.get('MEDIATYPE', ''), attr_dict.get('BUSPROTOCOL', '')
                                n = attr_dict.get('NAME', attr_dict.get('DEVICEDESCRIPTION', ''))
                                if sz and str(sz) not in ['0', '0 Bytes']:
                                    if str(sz).isdigit() and int(sz) > 1000000:
                                        gb = int(sz) / (1024**3)
                                        sz = f"{gb/1024:.2f} TB" if gb >= 1000 else f"{gb:.2f} GB"
                                    disk_list.append(f"[{n}] {sz} {md} {pr}".strip().replace("None", ""))
                            elif any(x in identity for x in ['RAID', 'AHCI', 'CONTROLLER']):
                                p = attr_dict.get('PRODUCTNAME', attr_dict.get('DEVICEDESCRIPTION', attr_dict.get('NAME')))
                                if p: controller_list.append(p)
                            elif 'NIC' in identity or 'ETHERNET' in identity:
                                p = attr_dict.get('PRODUCTNAME', attr_dict.get('DEVICEDESCRIPTION', attr_dict.get('NAME')))
                                if p: nic_list.append(p)
                            elif 'FC' in identity or 'FIBRECHANNEL' in identity:
                                p = attr_dict.get('PRODUCTNAME', attr_dict.get('DEVICEDESCRIPTION', attr_dict.get('NAME')))
                                if p: fc_list.append(p)
                    except: pass

        # จัดกลุ่มขึ้นบรรทัดใหม่
        if cpu_list: hardware_data['CPU'] = "\n".join(list(set(cpu_list)))
        if ram_list: hardware_data['RAM'] = "\n".join(list(set(ram_list)))
        if disk_list: hardware_data['Physical Disk'] = "\n".join(list(set(disk_list)))
        if controller_list: hardware_data['Controller Card'] = "\n".join(list(set(controller_list)))
        if nic_list: hardware_data['Interface LAN'] = "\n".join(list(set(nic_list)))
        if fc_list: hardware_data['FC Channel'] = "\n".join(list(set(fc_list)))
        
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผลไฟล์: {e}")
        
    return hardware_data

def export_to_docx(data):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    
    doc = Document()
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run("Lifecycle Log Summary Inventory")
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(26, 82, 118)
    
    table = doc.add_table(rows=1, cols=2)
    table.style = 'Table Grid'
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Hardware Component'
    hdr_cells[1].text = 'Details / Value'
    
    for cell in hdr_cells:
        cell.paragraphs[0].runs[0].font.bold = True
        cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'), "1A5276")
        tcPr.append(shd)
        
    for key, value in data.items():
        row_cells = table.add_row().cells
        row_cells[0].text = str(key)
        row_cells[1].text = str(value)
        row_cells[0].paragraphs[0].runs[0].font.bold = True
        
    docx_buffer = io.BytesIO()
    doc.save(docx_buffer)
    docx_buffer.seek(0)
    return docx_buffer

# ⚠️ ถ้าบรรทัดด้านล่างนี้หายไป หน้าเว็บจะกลายเป็นสีขาวทันทีครับ
st.set_page_config(page_title="TSR Log Hardware Extractor", page_icon="🖥️", layout="wide")
st.title("🖥️ TSR Log Hardware Extractor")
st.subheader("อัปโหลดไฟล์ Dell TSR Log (.zip) เพื่อดึงข้อมูล Inventory เสมือนในหน้า Lifecycle")

uploaded_file = st.file_uploader("เลือกไฟล์ TSR Log (.zip)", type=["zip"])

if uploaded_file is not None:
    st.success("โหลดไฟล์สำเร็จ! กำลังวิเคราะห์และดึงข้อมูล...")
    
    parsed_data = parse_tsr_log(uploaded_file)
    
    st.write("### 📊 Lifecycle Log Summary Inventory")
    table_rows = [{"Hardware Component": k, "Details / Value": v} for k, v in parsed_data.items()]
    st.table(table_rows)
    
    st.write("---")
    if st.button("🔄 คลิกที่นี่เพื่อเตรียมไฟล์ Word (.docx)"):
        try:
            docx_file = export_to_docx(parsed_data)
            st.download_button(
                label="📥 ดาวน์โหลดไฟล์ Word (.docx)",
                data=docx_file,
                file_name=f"Inventory_{parsed_data['Serial Number (Service Tag)']}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        except Exception as e:
            st.error(f"ไม่สามารถสร้างไฟล์ Word ได้: {e}")
