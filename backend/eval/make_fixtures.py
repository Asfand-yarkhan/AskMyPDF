"""Generate the synthetic PDFs used by the evaluation set (no real or personal data).

Run:  python -m eval.make_fixtures
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

FIXTURES = Path(__file__).parent / "fixtures"

HANDBOOK = [
    ("1. Leave Policy (POL-101)", [
        "Every full-time employee receives 22 days of paid annual leave per calendar year.",
        "Sick leave is granted for up to 10 days per year; a medical certificate is required after 2 consecutive days.",
        "Unused annual leave of up to 5 days may be carried over to the next year.",
    ]),
    ("2. Refund Policy (POL-104)", [
        "Customers may return products within 30 days of purchase for a full refund.",
        "A valid receipt or order number is required for every refund request.",
        "Refunds are issued to the original payment method within 7 business days.",
    ]),
    ("3. Remote Work (POL-207)", [
        "Employees may work remotely up to 3 days per week with their team lead's approval.",
        "A company VPN connection is mandatory whenever company systems are accessed remotely.",
    ]),
    ("4. Information Security (SEC-310)", [
        "Passwords must be at least 14 characters long and include a number and a symbol.",
        "Passwords must be rotated every 90 days; the last 5 passwords cannot be reused.",
        "Lost or stolen laptops must be reported to IT within 1 hour.",
    ]),
    ("5. Travel and Expenses (FIN-420)", [
        "Meal expenses are capped at 45 USD per day while travelling.",
        "Any single expense above 500 USD requires written approval from the employee's manager.",
        "Expense claims must be submitted within 14 days of the trip ending.",
    ]),
    ("6. Contacts", [
        "Human Resources can be reached at hr@northwind.example for leave and payroll questions.",
        "The IT help desk is available on extension 4455 from 9 AM to 6 PM.",
    ]),
]

# Fake student. Layout mirrors real result cards: header, course table, CGPA after the table,
# and semesters that spill across page breaks.
SEMESTERS = [
    ("Spring 2023", [("Introduction to ICT", 88, "A"), ("Calculus I", 74, "B")], "3.62"),
    ("Fall 2023", [("Programming Fundamentals", 91, "A"), ("Discrete Structures", 69, "B-")], "3.55"),
    ("Spring 2024", [("Data Structures", 82, "A-"), ("Digital Logic", 77, "B+")], "3.58"),
    ("Fall 2024", [("Operating Systems", 41, "F"), ("Databases", 85, "A")], "3.39"),
    ("Spring 2025", [("Operating Systems", 72, "B"), ("Computer Networks", 80, "A-")], "3.44"),
]


def _write_lines(page: pymupdf.Page, lines: list[tuple[str, float, bool]], y: float) -> float:
    for text, size, bold in lines:
        page.insert_text((60, y), text, fontsize=size, fontname="hebo" if bold else "helv")
        y += size + 9
    return y


def make_handbook(path: Path) -> None:
    pdf = pymupdf.open()
    for title, paragraphs in HANDBOOK:
        page = pdf.new_page()
        page.insert_text((60, 40), "Northwind Traders - Employee Handbook 2026", fontsize=8)
        y = _write_lines(page, [(title, 16, True)], 90)
        for para in paragraphs:
            box = pymupdf.Rect(60, y, 540, y + 60)
            page.insert_textbox(box, para, fontsize=11)
            y += 46
        page.insert_text((60, 810), f"Page {page.number + 1} of {len(HANDBOOK)}", fontsize=8)
    pdf.save(path)


def make_results(path: Path) -> None:
    pdf = pymupdf.open()
    page = pdf.new_page()
    y = _write_lines(page, [("Student Result Card", 15, True), ("Name: Ali Raza   Reg. No: DEMO-2023-001", 10, False)], 70)
    for name, courses, cgpa in SEMESTERS:
        block = [(f"Semester: {name}", 11, True), ("Course | Marks | Grade", 10, True)]
        block += [(f"{course} | {marks} | {grade}", 10, False) for course, marks, grade in courses]
        block += [(f"CGPA : {cgpa}", 10, True), ("Scholastic Status: Good", 10, False)]
        for line in block:
            if y > 760:  # spill to the next page like real portals do
                page = pdf.new_page()
                y = 70
            y = _write_lines(page, [line], y)
        y += 60
    pdf.save(path)


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    make_handbook(FIXTURES / "handbook.pdf")
    make_results(FIXTURES / "results.pdf")
    print(f"Wrote fixtures to {FIXTURES}")


if __name__ == "__main__":
    main()
