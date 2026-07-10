import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import json
import io
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# --- ฟังก์ชันการช่วยตั้งค่าพื้นหลังตารางใน Word (Shading) ---
def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    tcPr.append(shd)

# --- ฟังก์ชันหลักในการแกะข้อมูลจาก TSR Log (.zip) ---
def parse_tsr_log(uploaded_file):
    # กำหนดค่าเริ่มต้น (Default/Fallback Values) เผื่อกรณีหา Tag ไม่เจอ
    hardware_data = {
        "Model": "ไม่พบข้อมูล",
        "Serial Number (Service Tag)": "ไม่พบข้อมูล",
        "Hostname": "ไม่พบข้อมูล",
        "IP iDRAC": "ไม่พบข้อมูล",
        "CPU": "ไม่พบข้อมูล",
        "RAM": "ไม่พบข้อมูล",
        "Physical Disk": "ไม่พบข้อมูล",
        "Controller Card": "ไม่พบข้อมูล",
        "Interface LAN": "ไม่พบข้อมูล",
        "FC Channel": "ไม่พบข้อมูล"
    }
    
    try:
        with zipfile.ZipFile(uploaded_file, 'r') as z:
            file_list = z.namelist()
            
            # ตัวอย่างการค้นหาและอ่านไฟล์ภายใน TSR Zip
            # ใน TSR ของ Dell ข้อมูลมักจะอยู่ใน 'sysconfig.xml', 'inventory.xml' หรือไฟล์ JSON ในโฟลเดอร์ tsr/
            for file_name in file_list:
                # 1. ตัวอย่างการอ่านไฟล์ XML เพื่อดึงค่าพื้นฐาน
                if 'sysconfig.xml' in file_name.lower() or 'inventory.xml' in file_name.lower():
                    xml_content = z.read(file_name)
                    root = ET.fromstring(xml_content)
                    
                    # ตัวอย่าง Logic การดึงค่า (ปรับเปลี่ยนตามโครงสร้าง XML จริงของรุ่นนั้นๆ)
                    # For example only:
                    # if root.find(".//Model") is not None:
                    #     hardware_data["Model"] = root.find(".//Model").text
                    pass
                
                # 2. ตัวอย่างการอ่านไฟล์ JSON (iDRAC รุ่นใหม่ๆ)
                elif 'hardware_inventory.json' in file_name.lower():
                    json_content = json.loads(z.read(file_name).decode('utf-8'))
                    # ดึงค่าตาม Key ของ JSON
                    pass

            # --- ส่วนจำลองข้อมูลที่ดึงได้จาก TSR Log เพื่อแสดงผลบนหน้าเว็บ ---
            # (เมื่อนำไปใช้จริง สามารถเขียน Logic นำค่าที่ Parse ได้ด้านบนมาเขียนทับที่นี่)
            hardware_data["Model"] = "PowerEdge R750"
            hardware_data["Serial Number (Service Tag)"] = "9XPLK83"
            hardware_data["Hostname"] = "bkk-prod-db01"
            hardware_data["IP iDRAC"] = "192.168.10.45"
            hardware_data["CPU"] = "2x Intel(R) Xeon(R) Gold 6330 CPU @ 2.00GHz (56 Cores Total)"
            hardware_data["RAM"] = "512 GB (16x 32GB DDR4 3200MHz RDIMM)"
            hardware_data["Physical Disk"] = "4x 1.92TB NVMe SSD Read Intensive, 8x 2.4TB 10K RPM SAS HDD"
            hardware_data["Controller Card"] = "PERC H755 Front NVMe"
            hardware_data["Interface LAN"] = "2x 10GbE SFP+ LOM (Intel X710) + 4x 1GbE RJ45 Base-T"
            hardware_data["FC Channel"] = "2x QLogic 2772 Dual Port 32Gb Fibre Channel HBA"
            
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการอ่านไฟล์ TSR Log: {e}")
        
    return hardware_data

# --- ฟังก์ชันสร้างไฟล์ .docx ---
def export_to_docx(data):
    doc = Document()
    
    # กำหนดรูปแบบหัวข้อใหญ่
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run("Server Hardware Inventory Report")
    title_run.font.size = Pt(20)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(26, 82, 118) # สีกรมท่า/น้ำเงินเข้ม
    
    doc.add_paragraph("รายงานข้อมูลฮาร์ดแวร์ที่สกัดจากระบบ Technical Support Report (TSR Log)")
    
    # สร้างตารางข้อมูล 2 คอลัมน์
    table = doc.add_table(rows=1, cols=2)
    table.style = 'Table Grid'
    
    # หัวตาราง (Header)
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Hardware Component'
    hdr_cells[1].text = 'Details / Value'
    
    # ตกแต่ง Header
    for cell in hdr_cells:
        cell.paragraphs[0].runs[0].font.bold = True
        cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        set_cell_background(cell, "1A5276") # พื้นหลังหัวตารางสีกรมท่า
        
    # ใส่ข้อมูลลงในตาราง
    for key, value in data.items():
        row_cells = table.add_row().cells
        row_cells[0].text = str(key)
        row_cells[1].text = str(value)
        
        # ทำตัวหนาที่คอลัมน์แรกเพื่อความสวยงาม
        row_cells[0].paragraphs[0].runs[0].font.bold = True
        
    # บันทึกไฟล์ลงใน Memory (BytesIO) เพื่อให้ส่งดาวน์โหลดผ่านเว็บได้ทันที
    docx_buffer = io.BytesIO()
    doc.save(docx_buffer)
    docx_buffer.seek(0)
    return docx_buffer

# --- ส่วนการแสดงผลบนหน้าเว็บ (Streamlit UI) ---
st.set_page_config(page_title="TSR Log Hardware Inventory Extractor", page_icon="🖥️", layout="wide")

st.title("🖥️ TSR Log Hardware Inventory Extractor")
st.subheader("อัปโหลดไฟล์ Dell TSR Log (.zip) เพื่อดึงข้อมูลฮาร์ดแวร์สำคัญ")

uploaded_file = st.file_uploader("เลือกไฟล์ TSR Log (.zip)", type=["zip"])

if uploaded_file is not None:
    st.success("โหลดไฟล์สำเร็จ! กำลังทำการวิเคราะห์และดึงข้อมูล...")
    
    # เรียกฟังก์ชันอ่านไฟล์
    parsed_data = parse_tsr_log(uploaded_file)
    
    st.write("### 📊 ข้อมูลฮาร์ดแวร์ที่พบ (Hardware Inventory)")
    
    # แสดงผลในรูปแบบ Key-Value Key ในตารางเว็บแอป
    for key, val in parsed_data.items():
        st.markdown(f"**• {key}:** {val}")
        
    # สร้างไฟล์ Word
    docx_file = export_to_docx(parsed_data)
    
    st.write("---")
    # ปุ่มดาวน์โหลดไฟล์ .docx
    st.download_button(
        label="📥 Export เป็นไฟล์ Word (.docx)",
        data=docx_file,
        file_name=f"Hardware_Inventory_{parsed_data['Serial Number (Service Tag)']}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
