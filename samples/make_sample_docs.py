"""Make the fictional sample KYC documents used to demo AI document intake.

Run:  python samples/make_sample_docs.py   (needs reportlab: pip install reportlab)

Every person and company here is invented. Each page carries a SPECIMEN watermark.
The PDFs are committed, so this only needs running again if you change them; after a change, update
expected_results.json (the saved results the app uses when no API key is set).
"""

import hashlib
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent
W, H = A4


def _page(c, title, subtitle):
    c.setFillColor(colors.HexColor("#0B3D5C"))
    c.rect(0, H - 90, W, 90, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, H - 50, title)
    c.setFont("Helvetica", 10)
    c.drawString(40, H - 70, subtitle)
    c.saveState()
    c.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.12))
    c.setFont("Helvetica-Bold", 70)
    c.translate(W / 2, H / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "SPECIMEN")
    c.restoreState()
    c.setFillColor(colors.black)


def _rows(c, rows, y, label_w=190):
    for label, value in rows:
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(40, y, label)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40 + label_w, y, value)
        y -= 24
    return y


def _footer(c):
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.HexColor("#777777"))
    c.drawString(40, 30, "Fictional specimen made for the Sanad demo. Not a real document. Any resemblance is coincidental.")


def passport(path):
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    _page(c, "PASSPORT  /  PASAPORTE", "Kingdom of Spain  ·  Type P  ·  Specimen")
    c.setStrokeColor(colors.HexColor("#999999"))
    c.rect(40, H - 300, 120, 150)
    c.setFont("Helvetica", 9)
    c.drawCentredString(100, H - 230, "PHOTO")
    _rows(c, [
        ("Surname", "MARQUEZ DUARTE"),
        ("Given names", "SOFIA ELENA"),
        ("Nationality", "SPANISH"),
        ("Date of birth", "12 APR 1988"),
        ("Sex", "F"),
        ("Place of birth", "VALENCIA"),
        ("Passport no.", "PXA4471920"),
        ("Date of issue", "02 MAR 2015"),
        ("Date of expiry", "01 MAR 2025"),
        ("Profession", "INTERIOR DESIGNER"),
    ], H - 140, label_w=280)
    c.setFont("Courier-Bold", 12)
    c.drawString(40, 140, "P<ESPMARQUEZ<DUARTE<<SOFIA<ELENA<<<<<<<<<<<<<")
    c.drawString(40, 120, "PXA44719204ESP8804125F2503019<<<<<<<<<<<<<<06")
    _footer(c)
    c.save()


def trade_licence(path):
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    _page(c, "COMMERCIAL LICENCE", "Department of Economy and Tourism (specimen)  ·  Dubai, United Arab Emirates")
    y = _rows(c, [
        ("Licence no.", "DET-1187342"),
        ("Trade name", "FALCON BAY GENERAL TRADING L.L.C"),
        ("Legal form", "Limited Liability Company"),
        ("Issue date", "15/06/2021"),
        ("Expiry date", "14/06/2027"),
        ("Country", "United Arab Emirates"),
        ("Address", "Office 1204, Al Fahidi Tower, Bur Dubai"),
        ("Activities", "General Trading"),
        ("", "Electronics & Mobile Phones Trading"),
        ("Manager", "LAYLA HADDAD"),
    ], H - 140)
    _footer(c)
    c.save()


def moa(path):
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    _page(c, "MEMORANDUM OF ASSOCIATION", "FALCON BAY GENERAL TRADING L.L.C  ·  Specimen")
    text = c.beginText(40, H - 130)
    text.setFont("Helvetica", 10.5)
    text.setLeading(16)
    for line in [
        "On 10 June 2021 the following parties agreed to form a limited liability company under",
        "UAE Federal Decree-Law No. 32 of 2021 on Commercial Companies:",
        "",
        "Article 1. Name: Falcon Bay General Trading L.L.C",
        "Article 2. Head office: Dubai, United Arab Emirates",
        "Article 3. Objects: General trading; electronics and mobile phones trading.",
        "Article 4. Share capital: AED 300,000 divided into 300 shares of AED 1,000 each,",
        "held as follows:",
    ]:
        text.textLine(line)
    c.drawText(text)
    y = H - 280
    c.setFont("Helvetica-Bold", 10)
    for x, h in zip((40, 230, 350, 440, 500), ("Partner", "Nationality / Country", "Type", "Shares", "%")):
        c.drawString(x, y, h)
    c.setFont("Helvetica", 10)
    for row in [
        ("Layla Haddad", "Jordan", "Individual", "120", "40%"),
        ("Northwind Ventures Limited", "Seychelles", "Company", "105", "35%"),
        ("Omar Siddiqui", "India", "Individual", "75", "25%"),
    ]:
        y -= 20
        for x, v in zip((40, 230, 350, 440, 500), row):
            c.drawString(x, y, v)
    text = c.beginText(40, y - 40)
    text.setFont("Helvetica", 10.5)
    text.setLeading(16)
    for line in [
        "Article 5. Management: The company is managed by Layla Haddad (Jordan) as manager for an",
        "unlimited term. Rahul Menon (India) is appointed director of finance.",
        "Article 6. Profits and losses are shared in proportion to shareholding.",
        "",
        "Signed by the partners before the notary public, Dubai.",
    ]:
        text.textLine(line)
    c.drawText(text)
    _footer(c)
    c.save()


def main():
    files = {"sample_passport_sofia_marquez.pdf": passport,
             "sample_trade_licence_falcon_bay.pdf": trade_licence,
             "sample_moa_falcon_bay.pdf": moa}
    for name, fn in files.items():
        fn(HERE / name)
    for name in files:
        print(name, hashlib.sha256((HERE / name).read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
