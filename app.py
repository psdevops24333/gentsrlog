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
        with zipfile.ZipFile(uploaded_file, 'r') as z:
            all_files = z.namelist()
            
            # --- DEBUG: แสดงรายชื่อไฟล์ 15 ไฟล์แรกใน ZIP เพื่อตรวจสอบโครงสร้าง ---
            with st.expander("🔍 ดูโครงสร้างไฟล์ภายใน TSR ZIP (สำหรับตรวจสอบ)"):
                st.write(f"จำนวนไฟล์ทั้งหมดใน ZIP: {len(all_files)} ไฟล์")
                st.write("ตัวอย่างรายชื่อไฟล์ภายใน:")
                st.code("\n".join(all_files[:15]))
            
            # ค้นหาไฟล์เป้าหมาย (รองรับทั้ง XML และ JSON)
            inventory_xml_file = None
            inventory_json_file = None
            
            for fname in all_files:
                fname_lower = fname.lower()
                if 'inventory.xml' in fname_lower or 'hw_inventory.xml' in fname_lower:
                    inventory_xml_file = fname
                elif 'hardware_inventory.json' in fname_lower or 'hw_inventory.json' in fname_lower:
                    inventory_json_file = fname

            # -------------------------------------------------------------
            # ทางเลือกที่ 1: แกะไฟล์ JSON (สำหรับ iDRAC รุ่นใหม่/เฟิร์มแวร์ใหม่)
            # -------------------------------------------------------------
            if inventory_json_file:
                st.info(f"📂 ตรวจพบไฟล์ข้อมูลแบบ JSON: `{inventory_json_file}` กำลังประมวลผล...")
                json_data = json.loads(z.read(inventory_json_file).decode('utf-8', errors='ignore'))
                
                # พยายามดักจับข้อมูลแบบ Generic จาก JSON Object
                # ดึงจากโครงสร้างหลักของ Dell JSON
                system_inventory = json_data.get("SystemInventory", json_data)
                components = system_inventory.get("Component", [])
                if isinstance(components, dict):  # บางครั้งเป็น Object ตัวเดียว
                    components = [components]
                
                for comp in components:
                    fqdd = comp.get("@FQDD", comp.get("FQDD", ""))
                    attributes = comp.get("Attribute", [])
                    if isinstance(attributes, dict):
                        attributes = [attributes]
                        
                    attr_dict = {}
                    for attr in attributes:
                        name = attr.get("@Name", attr.get("Name"))
                        value = attr.get("#text", attr.get("Value", attr.get("text")))
                        if name and value:
                            attr_dict[name] = value

                    # ทำการ Map ข้อมูล
                    if "System.Board" in fqdd:
                        if "Model" in attr_dict: hardware_data["Model"] = attr_dict["Model"]
                        if "ServiceTag" in attr_dict: hardware_data["Serial Number (Service Tag)"] = attr_dict["ServiceTag"]
                    elif "iDRAC.Embedded" in fqdd and "HostName" in attr_dict:
                        hardware_data["Hostname"] = attr_dict["HostName"]
                    elif "IPv4." in fqdd and "Address" in attr_dict and attr_dict["Address"] != "0.0.0.0":
                        hardware_data["IP iDRAC"] = attr_dict["Address"]
                    elif "CPU.Socket" in fqdd and "Model" in attr_dict:
                        cpu_list.append(attr_dict["Model"])
                    elif "DIMM.Socket" in fqdd and attr_dict.get("Size") not in ["0 MB", "0", "-", None]:
                        ram_list.append(f"{attr_dict.get('Size')} ({attr_dict.get('Speed', '')})")
                    elif ("Disk." in fqdd or "PhysicalDisk." in fqdd) and "Size" in attr_dict:
                        disk_list.append(f"{attr_dict['Size']} {attr_dict.get('MediaType', '')}")
                    elif ("RAID." in fqdd or "AHCI." in fqdd) and "ProductName" in attr_dict:
                        controller_list.append(attr_dict["ProductName"])
                    elif "NIC." in fqdd and "ProductName" in attr_dict:
                        nic_list.append(attr_dict["ProductName"])
                    elif ("FC." in fqdd or "FibreChannel." in fqdd) and "ProductName" in attr_dict:
                        fc_list.append(attr_dict["ProductName"])

            # -------------------------------------------------------------
            # ทางเลือกที่ 2: แกะไฟล์ XML (สำหรับ iDRAC ทั่วไป)
            # -------------------------------------------------------------
            elif inventory_xml_file:
                st.info(f"📂 ตรวจพบไฟล์ข้อมูลแบบ XML: `{inventory_xml_file}` กำลังประมวลผล...")
                xml_content = z.read(inventory_xml_file)
                root = ET.fromstring(xml_content)
                
                # ลบ XML Namespaces
                for elem in root.iter():
                    if '}' in elem.tag:
                        elem.tag = elem.tag.split('}', 1)[1]
                
                for comp in root.findall('.//Component'):
                    fqdd = comp.get('FQDD', '')
                    
                    if 'System.Board' in fqdd:
                        for attr in comp.findall('Attribute'):
                            if attr.get('Name') == 'Model': hardware_data['Model'] = attr.text
                            if attr.get('Name') == 'ServiceTag': hardware_data['Serial Number (Service Tag)'] = attr.text
                    elif 'iDRAC.Embedded' in fqdd:
                        for attr in comp.findall('Attribute'):
                            if attr.get('Name') == 'HostName': hardware_data['Hostname'] = attr.text
                    elif 'IPv4.' in fqdd:
                        for attr in comp.findall('Attribute'):
                            if attr.get('Name') == 'Address' and attr.text != '0.0.0.0': 
                                hardware_data['IP iDRAC'] = attr.text
                    elif 'CPU.Socket' in fqdd:
                        model = comp.find("Attribute[@Name='Model']")
                        if model is not None: cpu_list.append(model.text)
                    elif 'DIMM.Socket' in fqdd:
                        size = comp.find("Attribute[@Name='Size']")
                        speed = comp.find("Attribute[@Name='Speed']")
                        if size is not None and size.text not in ['0 MB', '0', '-', 'None']:
                            ram_list.append(f"{size.text} ({speed.text if speed is not None else ''})")
                    elif 'Disk.' in fqdd or 'PhysicalDisk.' in fqdd:
                        size = comp.find("Attribute[@Name='Size']")
                        media = comp.find("Attribute[@Name='MediaType']")
                        if size is not None:
                            disk_list.append(f"{size.text} {media.text if media is not None else ''}")
                    elif 'RAID.' in fqdd or 'AHCI.' in fqdd:
                        prod = comp.find("Attribute[@Name='ProductName']")
                        if prod is not None: controller_list.append(prod.text)
                    elif 'NIC.' in fqdd:
                        prod = comp.find("Attribute[@Name='ProductName']")
                        if prod is not None: nic_list.append(prod.text)
                    elif 'FC.' in fqdd or 'FibreChannel.' in fqdd:
                        prod = comp.find("Attribute[@Name='ProductName']")
                        if prod is not None: fc_list.append(prod.text)
            
            else:
                st.warning("⚠️ ไม่พบไฟล์ `inventory.xml` หรือ `hardware_inventory.json` ในระบบกรุณาตรวจสอบไฟล์ ZIP")

        # สรุปผลข้อมูลจัดกลุ่ม (Grouping)
        if cpu_list: hardware_data['CPU'] = f"{len(cpu_list)}x {cpu_list[0]}"
        if ram_list: hardware_data['RAM'] = f"{len(ram_list)} DIMMs (เช่น {ram_list[0]})"
        if disk_list: hardware_data['Physical Disk'] = f"รวม {len(disk_list)} ลูก (เช่น {disk_list[0]})"
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
