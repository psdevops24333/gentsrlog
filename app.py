import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import json
import io

def parse_tsr_log(uploaded_file):
    hardware_data = {
        "Model": "-",
        "Serial Number (Service Tag)": "-",
        "Hostname": "-",
        "IP iDRAC": "-",
        "CPU": "-",
        "RAM": "-",
        "Physical Disk": "-",
        "Controller Card": "-",
        "Interface LAN": "-",
        "FC Channel": "-"
    }
    
    cpu_list, ram_list, disk_list = [], [], []
    nic_list, fc_list, controller_list = [], [], []
    
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

            with st.expander("🔍 ดูโครงสร้างไฟล์ภายใน TSR ZIP (สำหรับตรวจสอบ)"):
                st.write(f"จำนวนไฟล์ทั้งหมดที่ค้นหา: {len(target_files)} ไฟล์")
                st.code("\n".join(target_files[:30]))

            inventory_json_file = None
            xml_files_to_parse = []
            
            for fname in target_files:
                fname_lower = fname.lower()
                if 'hardware_inventory.json' in fname_lower or 'hw_inventory.json' in fname_lower:
                    inventory_json_file = fname
                    break
                if 'inventory.xml' in fname_lower or 'hw_inventory.xml' in fname_lower:
                    xml_files_to_parse = [fname]
                    break
                if 'sysinfo_' in fname_lower and fname_lower.endswith('.xml'):
                    xml_files_to_parse.append(fname)

            # --- จัดการไฟล์ JSON ---
            if inventory_json_file:
                st.info(f"📄 ตรวจพบไฟล์ข้อมูลแบบ JSON: `{inventory_json_file}`")
                json_data = json.loads(target_z.read(inventory_json_file).decode('utf-8', errors='ignore'))
                system_inventory = json_data.get("SystemInventory", json_data)
                components = system_inventory.get("Component", [])
                if isinstance(components, dict): components = [components]
                
                for comp in components:
                    fqdd = comp.get("@FQDD", comp.get("FQDD", ""))
                    attributes = comp.get("Attribute", [])
                    if isinstance(attributes, dict): attributes = [attributes]
                        
                    attr_dict = {attr.get("@Name", attr.get("Name")): attr.get("#text", attr.get("Value", attr.get("text"))) for attr in attributes if attr.get("@Name", attr.get("Name"))}

                    if "System.Board" in fqdd:
                        if "Model" in attr_dict: hardware_data["Model"] = attr_dict["Model"]
                        if "ServiceTag" in attr_dict: hardware_data["Serial Number (Service Tag)"] = attr_dict["ServiceTag"]
                    elif "iDRAC.Embedded" in fqdd and "HostName" in attr_dict:
                        hardware_data["Hostname"] = attr_dict["HostName"]
                    elif "IPv4." in fqdd and "Address" in attr_dict and attr_dict["Address"] != "0.0.0.0":
                        hardware_data["IP iDRAC"] = attr_dict["Address"]
                    elif "CPU.Socket" in fqdd and "Model" in attr_dict:
                        cpu_list.append(attr_dict["Model"])
                    elif "DIMM.Socket" in fqdd and attr_dict.get("Size") not in ["0 MB", "0", "0 Bytes", "-", None]:
                        ram_list.append(f"{attr_dict.get('Size')} ({attr_dict.get('Speed', '')})")
                    elif ("Disk." in fqdd or "PhysicalDisk." in fqdd) and "Size" in attr_dict:
                        disk_list.append(f"{attr_dict['Size']} {attr_dict.get('MediaType', '')}")
                    elif ("RAID." in fqdd or "AHCI." in fqdd) and "ProductName" in attr_dict:
                        controller_list.append(attr_dict["ProductName"])
                    elif "NIC." in fqdd and "ProductName" in attr_dict:
                        nic_list.append(attr_dict["ProductName"])
                    elif ("FC." in fqdd or "FibreChannel." in fqdd) and "ProductName" in attr_dict:
                        fc_list.append(attr_dict["ProductName"])

            # --- จัดการไฟล์ XML (แบบทะลวง Property/Value) ---
            elif xml_files_to_parse:
                st.info(f"📄 ตรวจพบไฟล์ Inventory แยกส่วนจำนวน {len(xml_files_to_parse)} ไฟล์ (กำลังสกัดข้อมูลแบบลึกสุดขีด...)")

                for fname in xml_files_to_parse:
                    try:
                        xml_content = target_z.read(fname)
                        root = ET.fromstring(xml_content)
                        
                        # ลบ Namespace
                        for elem in root.iter():
                            if '}' in elem.tag:
                                elem.tag = elem.tag.split('}', 1)[1]
                        
                        for comp in root.iter():
                            attr_dict = {}
                            
                            # เก็บ Attribute ของตัวมันเอง
                            for k, v in comp.attrib.items():
                                attr_dict[k.upper()] = str(v).strip()
                                
                            # แกะข้อมูลลูก (จัดการโครงสร้าง Property/Value)
                            for child in comp:
                                tag = child.tag.split('}')[-1].upper()
                                name_attr = child.get('Name') or child.get('NAME')
                                
                                if tag in ['PROPERTY', 'ATTRIBUTE'] and name_attr:
                                    key = name_attr.upper()
                                    val_text = ""
                                    # หาค่าในแท็ก <Value>
                                    for sub in child:
                                        if sub.tag.split('}')[-1].upper() == 'VALUE' and sub.text:
                                            val_text = sub.text.strip()
                                    if val_text:
                                        attr_dict[key] = val_text
                                    elif child.text and child.text.strip():
                                        attr_dict[key] = child.text.strip()
                                else:
                                    if child.text and child.text.strip():
                                        attr_dict[tag] = child.text.strip()
                            
                            comp_tag = comp.tag.split('}')[-1].upper()
                            identity = attr_dict.get('INSTANCEID', attr_dict.get('FQDD', attr_dict.get('DEVICEID', comp_tag))).upper()

                            # กรองเฉพาะโหนดที่เป็นอุปกรณ์
                            if identity not in ['PROPERTY', 'VALUE', 'ATTRIBUTE']:
                                
                                # System / Board
                                if 'SYSTEM' in identity or 'BOARD' in identity or 'DCIM_SYSTEMVIEW' in identity:
                                    if attr_dict.get('MODEL') and hardware_data['Model'] == '-': hardware_data['Model'] = attr_dict['MODEL']
                                    if attr_dict.get('SERVICETAG') and hardware_data['Serial Number (Service Tag)'] == '-': hardware_data['Serial Number (Service Tag)'] = attr_dict['SERVICETAG']
                                    if attr_dict.get('HOSTNAME') and hardware_data['Hostname'] == '-': hardware_data['Hostname'] = attr_dict['HOSTNAME']
                                    
                                # IP iDRAC
                                elif 'IPV4' in identity or 'IDRAC' in identity:
                                    ip = attr_dict.get('CURRENTIPADDRESS', attr_dict.get('ADDRESS'))
                                    if ip and ip not in ['0.0.0.0', '::', '127.0.0.1'] and hardware_data['IP iDRAC'] == '-':
                                        hardware_data['IP iDRAC'] = ip
                                        
                                # CPU
                                elif 'CPU' in identity:
                                    model = attr_dict.get('MODEL', attr_dict.get('DEVICEDESCRIPTION', attr_dict.get('NAME')))
                                    if model: cpu_list.append(model)
                                        
                                # RAM
                                elif 'DIMM' in identity or 'MEMORY' in identity:
                                    size = attr_dict.get('SIZE', attr_dict.get('CAPACITY'))
                                    speed = attr_dict.get('SPEED', attr_dict.get('OPERATINGSPEED', ''))
                                    if size and str(size) not in ['0', '0 MB', '0 Bytes', 'None', '-']:
                                        ram_list.append(f"{size} ({speed})" if speed else str(size))
                                        
                                # Physical Disk
                                elif 'DISK' in identity or 'PHYSICALDISK' in identity:
                                    size = attr_dict.get('SIZE', attr_dict.get('SIZEINBYTES', attr_dict.get('CAPACITY')))
                                    media = attr_dict.get('MEDIATYPE', '')
                                    if size and str(size) not in ['0', '0 Bytes']:
                                        disk_list.append(f"{size} {media}".strip())
                                        
                                # Controller Card
                                elif 'RAID' in identity or 'AHCI' in identity or 'CONTROLLER' in identity:
                                    prod = attr_dict.get('PRODUCTNAME', attr_dict.get('DEVICEDESCRIPTION', attr_dict.get('NAME')))
                                    if prod: controller_list.append(prod)
                                        
                                # NIC
                                elif 'NIC' in identity or 'ETHERNET' in identity:
                                    prod = attr_dict.get('PRODUCTNAME', attr_dict.get('DEVICEDESCRIPTION', attr_dict.get('NAME')))
                                    if prod: nic_list.append(prod)
                                        
                                # FC Channel
                                elif 'FC' in identity or 'FIBRECHANNEL' in identity:
                                    prod = attr_dict.get('PRODUCTNAME', attr_dict.get('DEVICEDESCRIPTION', attr_dict.get('NAME')))
                                    if prod: fc_list.append(prod)
                    except Exception as e:
                        pass

            else:
                st.warning("⚠️ ไม่พบแฟ้มข้อมูลฮาร์ดแวร์ภายในไฟล์ ZIP นี้")

        # สรุปกลุ่มข้อมูลฮาร์ดแวร์ (ตัดตัวซ้ำทิ้ง)
        if cpu_list: 
            unique_cpus = list(set(cpu_list))
            hardware_data['CPU'] = f"{len(cpu_list)}x {unique_cpus[0]}" if unique_cpus else cpu_list[0]
        if ram_list: 
            hardware_data['RAM'] = f"{len(ram_list)} DIMMs (เช่น {ram_list[0]})"
        if disk_list: 
            unique_disks = list(set(disk_list))
            hardware_data['Physical Disk'] = f"รวม {len(disk_list)} ลูก ({', '.join(unique_disks[:2])}...)" if unique_disks else "-"
        if controller_list: hardware_data['Controller Card'] = ", ".join(list(set(controller_list)))
        if nic_list: hardware_data['Interface LAN'] = ", ".join(list(set(nic_list)))
        if fc_list: hardware_data['FC Channel'] = ", ".join(list(set(fc_list)))
        
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
