"""
Generate a PDF version of the Leave of Absence policy for the corpus.
Run once: python corpus/generate_pdf.py
Requires: pip install reportlab
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
import os

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "pdf", "10-leave-of-absence-policy.pdf")
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT_PATH,
        pagesize=letter,
        rightMargin=1*inch,
        leftMargin=1*inch,
        topMargin=1*inch,
        bottomMargin=1*inch
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=18, spaceAfter=6)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=4)
    h3_style = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11, spaceBefore=10, spaceAfter=3)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=6)
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=9, textColor=colors.grey, spaceAfter=4)
    bullet_style = ParagraphStyle("Bullet", parent=body_style, leftIndent=20, bulletIndent=10)

    content = []

    content.append(Paragraph("Leave of Absence Policy", title_style))
    content.append(Paragraph("Document ID: POL-HR-010", meta_style))
    content.append(Paragraph("Effective Date: January 1, 2025", meta_style))
    content.append(Paragraph("Last Reviewed: September 1, 2025", meta_style))
    content.append(Paragraph("Owner: Human Resources &amp; Legal", meta_style))
    content.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey, spaceAfter=12))

    content.append(Paragraph("1. Overview", h2_style))
    content.append(Paragraph(
        "Acme Corp provides various types of leave to eligible employees in accordance with federal and applicable "
        "state laws, and in support of employee well-being. This policy covers medical leave, family leave, "
        "military leave, personal leave, and bereavement leave.",
        body_style
    ))

    content.append(Paragraph("2. Family and Medical Leave (FMLA)", h2_style))
    content.append(Paragraph(
        "Employees who have worked at Acme Corp for at least 12 months and logged at least 1,250 hours in the "
        "past 12 months are eligible for up to <b>12 weeks of unpaid, job-protected leave</b> per year under "
        "the Family and Medical Leave Act (FMLA) for the following reasons:",
        body_style
    ))
    for reason in [
        "Birth, adoption, or foster placement of a child.",
        "Serious health condition of the employee.",
        "Serious health condition of a spouse, child, or parent.",
        "Qualifying exigency related to a family member's military service.",
    ]:
        content.append(Paragraph(f"• {reason}", bullet_style))

    content.append(Paragraph("2.1 Notice Requirements", h3_style))
    content.append(Paragraph(
        "When leave is foreseeable, employees must provide at least <b>30 days' advance notice</b>. "
        "When leave is unforeseeable, employees must notify HR as soon as practicable (typically within 1–2 business days).",
        body_style
    ))

    content.append(Paragraph("2.2 Interaction with PTO", h3_style))
    content.append(Paragraph(
        "Acme Corp requires employees to use any accrued PTO concurrently with unpaid FMLA leave. "
        "Using PTO does not extend the 12-week FMLA entitlement.",
        body_style
    ))

    content.append(Paragraph("3. Parental Leave", h2_style))
    content.append(Paragraph(
        "Separate from FMLA, Acme Corp provides paid parental leave to eligible employees (employed for at least 6 months):",
        body_style
    ))

    table_data = [
        ["Caregiver Role", "Paid Leave Duration"],
        ["Primary caregiver (birth, adoption, foster)", "12 weeks fully paid"],
        ["Secondary caregiver", "4 weeks fully paid"],
    ]
    t = Table(table_data, colWidths=[3.5*inch, 3*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2B6CB0")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#F7F9FC"), colors.white]),
        ("GRID", (0,0), (-1,-1), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    content.append(t)
    content.append(Spacer(1, 10))

    content.append(Paragraph("4. Military Leave", h2_style))
    content.append(Paragraph(
        "Acme Corp complies with the Uniformed Services Employment and Reemployment Rights Act (USERRA). "
        "Employees called to active duty or reserve training are entitled to unpaid leave for the duration of "
        "their service. Acme Corp will supplement military pay up to the employee's regular base salary for "
        "up to <b>30 days per year</b>.",
        body_style
    ))

    content.append(Paragraph("5. Personal Leave", h2_style))
    content.append(Paragraph(
        "Employees who have exhausted all PTO and do not qualify for FMLA may request an unpaid personal "
        "leave of absence of up to <b>4 weeks</b> with manager and HR approval. Personal leave is not guaranteed "
        "and is granted at the company's discretion based on business need.",
        body_style
    ))

    content.append(Paragraph("6. Bereavement Leave", h2_style))

    bv_data = [
        ["Relationship", "Paid Bereavement Days"],
        ["Spouse, domestic partner, child", "5 days"],
        ["Parent, sibling, grandparent, grandchild", "3 days"],
        ["In-law (parent, sibling)", "2 days"],
        ["Other close relation / chosen family", "1 day (manager discretion)"],
    ]
    bv = Table(bv_data, colWidths=[3.5*inch, 3*inch])
    bv.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2B6CB0")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#F7F9FC"), colors.white]),
        ("GRID", (0,0), (-1,-1), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    content.append(bv)
    content.append(Spacer(1, 10))
    content.append(Paragraph(
        "Additional unpaid bereavement time may be approved by the manager in extenuating circumstances. "
        "Employees may also use PTO to supplement bereavement leave.",
        body_style
    ))

    content.append(Paragraph("7. Requesting Leave", h2_style))
    for step in [
        "Notify your manager as soon as you are aware of the need for leave.",
        "Submit a leave request in Workday (Time Off &gt; Leave of Absence).",
        "HR will send the appropriate paperwork within 2 business days.",
        "For FMLA: provide medical certification from a healthcare provider within 15 calendar days.",
        "HR will confirm leave approval, start date, and return-to-work date in writing.",
    ]:
        content.append(Paragraph(f"• {step}", bullet_style))

    content.append(Paragraph("8. Return to Work", h2_style))
    content.append(Paragraph(
        "Employees returning from FMLA leave are entitled to return to the same or an equivalent position. "
        "Employees returning from personal leave are entitled to the same position only if it has not been "
        "eliminated due to business restructuring during the leave period. A fitness-for-duty certification "
        "may be required before returning from medical leave.",
        body_style
    ))

    content.append(Paragraph("9. Contact", h2_style))
    content.append(Paragraph("Leave requests and questions: hr@acmecorp.example.com", body_style))
    content.append(Paragraph("HR Benefits team: benefits@acmecorp.example.com", body_style))

    doc.build(content)
    print(f"PDF generated: {OUTPUT_PATH}")

if __name__ == "__main__":
    build_pdf()
