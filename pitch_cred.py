from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

W, H = A4

def np(c):
    c.showPage()

def bg(c, col):
    c.setFillColor(HexColor(col))
    c.rect(0,0,W,H,fill=1,stroke=0)

def txt(c, s, x, y, sz=12, b=False, col="#374151"):
    c.setFillColor(HexColor(col))
    c.setFont("Helvetica-Bold" if b else "Helvetica", sz)
    c.drawString(x, y, s)

def ln(c, y):
    c.setStrokeColor(HexColor("#312e81"))
    c.setLineWidth(2)
    c.line(30*mm, y, W-30*mm, y)

ML=30*mm
YR=H-25*mm
Y1=H-42*mm
YS=H-80*mm
YB=25*mm

def slide_title(c):
    bg(c,"#1e1b4b")
    txt(c,"DJANTA INNOV'ACTION 2026",ML,H-30*mm,14,True,"#a5b4fc")
    txt(c,"Credo",ML,H-55*mm,52,True,"#ffffff")
    txt(c,"AI Credit Broker for Financial Inclusion",ML,H-70*mm,20,False,"#ffffff")
    txt(c,"Origin SARL  |  Lome, Togo  |  credo.originafrika.online",ML,H-90*mm,12,False,"#a5b4fc")

def slide_problem(c):
    bg(c,"#ffffff")
    txt(c,"THE PROBLEM",ML,YR,14,True,"#dc2626")
    txt(c,"80% of Togo's economy is informal",ML,Y1,30,True)
    items=[
        "8M adults with no access to formal credit",
        "No payslip, no bank statement, no credit history",
        "Banks and MFIs reject due to lack of adapted tools",
        "Borrowers waste days queuing at agencies",
        "10.9% NPL rate from lack of standardized scoring",
        "New 2026 microfinance law demands better risk management"
    ]
    y=YS
    for i in items:
        txt(c,f"\u2022  {i}",ML+3*mm,y,12)
        y-=10*mm

def slide_solution(c):
    bg(c,"#ffffff")
    txt(c,"OUR SOLUTION",ML,YR,14,True,"#059669")
    txt(c,"Credo - AI Credit Broker in 5 Minutes",ML,Y1,28,True)
    items=[
        "User pays 2,500-5,000 FCFA via Mobile Money",
        "Answers adaptive questions in an AI chat",
        "AI analyzes profile via RAG multi-institution engine",
        "Result: score, max amount, recommended institution",
        "Personalized advice to improve solvability",
        "Zero displacement, zero bank account required",
        "MVP live in production: credo.originafrika.online"
    ]
    y=YS
    for i in items:
        txt(c,f"\u2022  {i}",ML+3*mm,y,12)
        y-=10*mm

def slide_innovation(c):
    bg(c,"#ffffff")
    txt(c,"INNOVATION",ML,YR,14,True,"#7c3aed")
    txt(c,"First AI Credit Broker in Togo",ML,Y1,28,True)
    items=[
        "RAG architecture: partner evaluation criteria embedded",
        "Mobile Money payment integrated (Flooz, Moov, TMoney)",
        "Adaptive chat that asks the right questions per profile",
        "Smart matching: optimal institution for each borrower",
        "Works for informal workers with no banking history",
        "No direct competitor identified in West Africa"
    ]
    y=YS
    for i in items:
        txt(c,f"\u2022  {i}",ML+3*mm,y,12)
        y-=10*mm

def slide_impact(c):
    bg(c,"#ffffff")
    txt(c,"IMPACT",ML,YR,14,True,"#0891b2")
    txt(c,"Transforming Financial Inclusion",ML,Y1,28,True)
    items=[
        "8M+ Togolese can check their solvability from their phone",
        "Reduced NPL through borrower-institution matching",
        "MFIs receive pre-validated, qualified leads",
        "Aggregated informal sector data for regulators",
        "Scalable architecture for all 8 WAEMU countries",
        "Target: 10,000 reports/month within 12 months"
    ]
    y=YS
    for i in items:
        txt(c,f"\u2022  {i}",ML+3*mm,y,12)
        y-=10*mm

def slide_team(c):
    bg(c,"#1e1b4b")
    txt(c,"THE TEAM",ML,H-30*mm,28,True,"#ffffff")
    txt(c,"David Fesal Peteou",ML,H-55*mm,16,True,"#ffffff")
    txt(c,"21-year-old developer. AI & Blockchain at College de Paris (2 yrs).",ML,H-65*mm,11,False,"#c7d2fe")
    txt(c,"Specializes in application architecture, database design, full-stack.",ML,H-73*mm,11,False,"#c7d2fe")
    txt(c,"Driven by closing Africa's technological gap.",ML,H-81*mm,11,False,"#c7d2fe")
    txt(c,"Manasse Peteou",ML,H-98*mm,16,True,"#ffffff")
    txt(c,"18 years, scientific baccalaureate. Self-taught developer.",ML,H-108*mm,11,False,"#c7d2fe")
    txt(c,"Skills comparable to 3 years experience. Rigor and reliability.",ML,H-116*mm,11,False,"#c7d2fe")
    txt(c,"Passionate about tech architecture and artificial intelligence.",ML,H-124*mm,11,False,"#c7d2fe")
    txt(c,"Gloria C.S. Yededji",ML,H-141*mm,16,True,"#ffffff")
    txt(c,"21-year-old Ivorian. Bachelor in Banking, Finance & Digital Studies.",ML,H-151*mm,11,False,"#c7d2fe")
    txt(c,"Experienced in financial analysis at CDP. Currently in Dubai.",ML,H-159*mm,11,False,"#c7d2fe")
    txt(c,"Role: partner communication, public image, commercial management.",ML,H-167*mm,11,False,"#c7d2fe")

def slide_traction(c):
    bg(c,"#ffffff")
    txt(c,"TRACTION",ML,H-30*mm,28,True)
    ln(c,H-43*mm)
    items=[
        "MVP in production: credo.originafrika.online",
        "Vercel deployment with automated CI/CD pipeline",
        "Mobile Money payment integrated",
        "RAG architecture ready for partner criteria ingestion",
        "Origin SARL incorporated (September 2025)",
        "Network: advisor close to the Togolese presidency"
    ]
    y=H-65*mm
    for i in items:
        txt(c,f"\u2022  {i}",ML+3*mm,y,13,False,"#1e1b4b")
        y-=12*mm

def slide_ask(c):
    bg(c,"#1e1b4b")
    txt(c,"OUR REQUEST",ML,H-35*mm,28,True,"#ffffff")
    txt(c,"Innov'Action Program",ML,H-58*mm,20,False,"#ffffff")
    txt(c,"6-Month Incubation + Start Fund Micro-Grant",ML,H-78*mm,24,True,"#a5b4fc")
    txt(c,"Goal: solidify the product, sign 3 MFI partnerships,",ML,H-100*mm,13,False,"#c7d2fe")
    txt(c,"reach 10K users, and prepare for scale across WAEMU.",ML,H-113*mm,13,False,"#c7d2fe")
    txt(c,"Credo  |  Origin SARL  |  July 2026",ML,YB,10,False,"#a5b4fc")

c=canvas.Canvas("C:\\Users\\junio\\Desktop\\FounderHQ\\Workspace\\Ventures\\Origin\\Credo\\Credo_Pitch_Deck.pdf",pagesize=A4)
c.setTitle("Credo - Pitch Deck")
c.setAuthor("Origin SARL")

slide_title(c);np(c);slide_problem(c);np(c);slide_solution(c);np(c);slide_innovation(c);np(c);slide_impact(c);np(c);slide_team(c);np(c);slide_traction(c);np(c);slide_ask(c)
c.save()
print("PDF OK")
