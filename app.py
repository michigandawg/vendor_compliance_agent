import os
import asyncio
import sqlite3
import shutil
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pypdf import PdfReader

# ==========================================
# DATABASE SETUP & SAVING LOGIC
# ==========================================
def setup_database():
    conn = sqlite3.connect('vendor_compliance.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approved_vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            legal_business_name TEXT,
            tax_id TEXT,
            effective_date TEXT,
            expiration_date TEXT,
            liability_limit INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def save_approved_vendor(data):
    conn = sqlite3.connect('vendor_compliance.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO approved_vendors (
            legal_business_name, tax_id, effective_date, expiration_date, liability_limit
        ) VALUES (?, ?, ?, ?, ?)
    ''', (
        data.legal_business_name, 
        data.tax_id, 
        str(data.effective_date), 
        str(data.expiration_date), 
        data.general_liability_limit
    ))
    conn.commit()
    conn.close()
    print(f"\n💾 SUCCESS: {data.legal_business_name} securely saved to database.")

# ==========================================
# NODE 1: DATA EXTRACTION SCHEMA
# ==========================================
class VendorComplianceSchema(BaseModel):
    legal_business_name: str = Field(..., description="Exact legal name of the vendor entity.")
    tax_id: str = Field(..., description="9-digit EIN or Tax ID (Format: XX-XXXXXXX).")
    effective_date: date = Field(..., description="The start date of the contract.")
    expiration_date: date = Field(..., description="The end date of the contract.")
    auto_renewal_clause: bool = Field(..., description="True if the contract auto-renews, False if not.")
    termination_notice_days: int = Field(..., description="Number of days notice required to cancel.")
    total_contract_value: Optional[str] = Field(None, description="Total cost or payment terms (e.g., 'Net 30').")
    general_liability_limit: int = Field(..., description="Max dollar amount of General Liability Insurance.")
    indemnification_cap: Optional[int] = Field(None, description="Maximum dollar amount the vendor can be sued for.")
    data_privacy_flag: bool = Field(..., description="True if the contract involves personal data.")
    missing_critical_data: bool = Field(default=False, description="Set to True ONLY IF required fields are missing.")

model = OpenAIChatModel('gpt-4o')

extraction_agent = Agent(
    model,
    instructions=(
        "You are a strict compliance auditor. Read the provided contract text and "
        "extract the exact information required by the schema. Do not guess. "
        "If a required field is completely missing, flag missing_critical_data as True."
    ),
    output_type=VendorComplianceSchema
)

# ==========================================
# NODE 4: THE REJECTION EMAIL AGENT
# ==========================================
rejection_agent = Agent(
    model,
    instructions=(
        "You are a professional legal compliance officer. Write a polite but firm "
        "email to a vendor explaining that their contract cannot be approved yet. "
        "List the exact compliance flags provided to you as bullet points they must fix."
    )
)

# ==========================================
# NODE 2: PURE PYTHON RULE ENGINE
# ==========================================
def compliance_rule_engine(extracted_data: VendorComplianceSchema) -> dict:
    report = {
        "passed_all_rules": True,
        "flags": []
    }

    if extracted_data.general_liability_limit < 1000000:
        report["passed_all_rules"] = False
        report["flags"].append(f"Liability too low: ${extracted_data.general_liability_limit:,}. Minimum required is $1,000,000.")

    if extracted_data.auto_renewal_clause is True:
        report["passed_all_rules"] = False
        report["flags"].append("Auto-renewal clause detected. This requires human override.")

    if extracted_data.termination_notice_days < 30:
        report["passed_all_rules"] = False
        report["flags"].append(f"Termination notice too short: {extracted_data.termination_notice_days} days.")

    return report

def extract_text_from_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

# ==========================================
# NEW: THE BATCH PROCESSING QUEUE
# ==========================================
async def process_inbox():
    setup_database()
    
    # 1. Automatically create our conveyor belt folders
    os.makedirs("Inbox", exist_ok=True)
    os.makedirs("Processed", exist_ok=True)
    
    # 2. Look for PDFs in the Inbox
    pdf_files = [f for f in os.listdir("Inbox") if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print("\n📭 The Inbox is empty. Drag some PDF contracts into the 'Inbox' folder and run me again.")
        return

    print(f"\n📦 Found {len(pdf_files)} contract(s) in the Inbox. Starting batch processing...\n")
    
    # 3. Loop through every file
    for index, filename in enumerate(pdf_files, start=1):
        file_path = os.path.join("Inbox", filename)
        
        print("=" * 60)
        print(f"📄 Processing {index} of {len(pdf_files)}: {filename}")
        print("=" * 60)
        
        real_contract_text = extract_text_from_pdf(file_path)

        result = await extraction_agent.run(real_contract_text)
        extracted_data = result.output
        
        if extracted_data.missing_critical_data:
            print("🛑 NODE 1 GATE FAILED: Contract is missing fields. Handoff to human review.")
        else:
            print("✅ NODE 1 GATE PASSED: All fields extracted perfectly.")

            audit_report = compliance_rule_engine(extracted_data)
            
            if audit_report["passed_all_rules"]:
                print("✅ 100% COMPLIANT: Contract meets all company standards. Auto-Approved.")
                save_approved_vendor(extracted_data)
            else:
                print("⚠️ COMPLIANCE FLAGS DETECTED:")
                for flag in audit_report["flags"]:
                    print(f"  -> {flag}")
                
                print("\n🛑 ROUTING TO HUMAN REVIEW QUEUE")
                decision = input("\nType 'APPROVE' to override or 'REJECT' to decline this vendor: ").strip().upper()
                
                if decision == 'APPROVE':
                    print("\n🟢 OVERRIDE ACCEPTED: Vendor approved by Human.")
                    save_approved_vendor(extracted_data)
                    
                elif decision == 'REJECT':
                    print("\n🔴 REJECTED: Generating professional rejection report...")
                    flags_text = "\n".join(audit_report["flags"])
                    prompt_for_agent = f"Draft an email for {extracted_data.legal_business_name}. Here are the flags:\n{flags_text}"
                    rejection_result = await rejection_agent.run(prompt_for_agent)
                    print("\n✉️ --- DRAFTED EMAIL TO VENDOR --- ✉️\n")
                    print(rejection_result.output)
                    print("\n-------------------------------------")
                else:
                    print("\n❌ Invalid input. Skipping this file.")

        # 4. Move the completed file off the assembly line
        processed_path = os.path.join("Processed", filename)
        shutil.move(file_path, processed_path)
        print(f"✅ Moved {filename} to the Processed folder.\n")

    print("🎉 BATCH COMPLETE: All files in the Inbox have been processed.")

if __name__ == "__main__":
    asyncio.run(process_inbox())