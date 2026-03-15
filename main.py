import os
import uuid
import pdfplumber
import re
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = FastAPI()

# NU Grade Mapping
GRADE_POINTS = {'A+': 4.00, 'A': 3.75, 'A-': 3.50, 'B+': 3.25, 'B': 3.00, 'B-': 2.75, 'C+': 2.50, 'C': 2.25, 'D': 2.00, 'F': 0.00}

# Use /tmp for production (Render/Koyeb requirement)
TMP_DIR = "/tmp" if os.environ.get("RENDER") else "uploads"
if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR)

def generate_report(student, courses, gpa, filename):
    path = os.path.join(TMP_DIR, filename)
    doc = SimpleDocTemplate(path, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph("<b>NATIONAL UNIVERSITY BANGLADESH</b>", styles['Title']))
    elements.append(Paragraph(f"<b>Name:</b> {student['name']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Reg No:</b> {student['reg']}", styles['Normal']))
    elements.append(Spacer(1, 15))
    data = [["Code", "Course Title", "Credit", "Grade", "GP"]]
    for c in courses:
        data.append([c['code'], c['title'], c['credit'], c['grade'], f"{c['gp']:.2f}"])
    t = Table(data, colWidths=[60, 270, 50, 50, 45])
    t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.blue), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
    elements.append(t)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"<b>FINAL GPA: {gpa}</b>", styles['Heading1']))
    doc.build(elements)
    return filename

@app.get("/")
async def home():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.post("/process")
async def process_pdf(file: UploadFile = File(...)):
    unique_id = uuid.uuid4().hex[:8]
    input_path = os.path.join(TMP_DIR, f"in_{unique_id}.pdf")
    
    with open(input_path, "wb") as buffer:
        buffer.write(await file.read())

    student_info = {"name": "Unknown", "reg": "Unknown"}
    all_courses = []

    try:
        with pdfplumber.open(input_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text: continue
                
                # Info Extraction
                for line in text.split('\n'):
                    if "Name" in line: student_info['name'] = line.split("Name")[-1].replace(":","").strip()
                    if "Registration" in line: 
                        regs = re.findall(r'\d+', line)
                        if regs: student_info['reg'] = regs[0]

                # Result Extraction (Regex Fallback included)
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        row = [str(c).strip() if c else "" for c in row]
                        if len(row) >= 4:
                            code, credit_str, grade = row[0], row[-2], row[-1].upper()
                            if credit_str.isdigit() and grade in GRADE_POINTS:
                                all_courses.append({"code": code, "title": row[1], "credit": int(credit_str), "grade": grade, "gp": GRADE_POINTS[grade]})

                if len(all_courses) < 1:
                    regex_pattern = r"(\d{6})\s+(.*?)\s+(\d)\s+([A-F][+-]?)"
                    matches = re.findall(regex_pattern, text)
                    for m in matches:
                        if m[3] in GRADE_POINTS:
                            all_courses.append({"code": m[0], "title": m[1].strip(), "credit": int(m[2]), "grade": m[3], "gp": GRADE_POINTS[m[3]]})

        if not all_courses:
            return JSONResponse(status_code=400, content={"message": "No results found."})

        total_pts = sum(c['gp'] * c['credit'] for c in all_courses)
        total_credits = sum(c['credit'] for c in all_courses)
        gpa = round(total_pts / total_credits, 2)

        report_file = generate_report(student_info, all_courses, gpa, f"Result_{unique_id}.pdf")

        return {
            "status": "success",
            "student": student_info,
            "courses": all_courses,
            "gpa": gpa,
            "download_url": f"/download/{report_file}"
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@app.get("/download/{filename}")
async def download(filename: str):
    file_path = os.path.join(TMP_DIR, filename)
    return FileResponse(file_path)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)