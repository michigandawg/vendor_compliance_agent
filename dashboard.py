import os
import smtplib
from email.message import EmailMessage
import pandas as pd
import streamlit as st
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pypdf import PdfReader
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Vendor Compliance Hub", layout="wide")

# ==========================================
# ENTERPRISE SECURITY GATE
# ==========================================
def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["ADMIN_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't store password in session
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔐 Secure Enterprise Portal")
        st.markdown("Unauthorized access is strictly prohibited. Please enter your administrator token.")
        st.text_input("Access Token", type="password", on_change=password_entered, key="password")
        return False
    
    elif not st.session_state["password_correct"]:
        st.title("🔐 Secure Enterprise Portal")
        st.markdown("Unauthorized access is strictly prohibited. Please enter your administrator token.")
        st.text_input("Access Token", type="password", on_change=password_entered, key="password")
        st.error("🔒 Authentication failed. Incorrect token.")
        return False
    
    return True

# STOP EXECUTION IF NOT AUTHENTICATED
if not check_password():
    st.stop()

# ==========================================
# ENTERPRISE DATABASE CLOUD CONNECTION
# ==========================================
try:
    db_url = st.secrets["DATABASE_URL"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    # Tell SQLAlchemy to use the pure-Python pg8000 driver
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+pg8000://", 1)
except Exception as e:
    st.error("⚠️ System halted: DATABASE_URL not found in Streamlit Secrets.")
    st.stop()

engine = create_engine(db_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ApprovedVendor(Base):
    __tablename__ = "approved_vendors"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    legal_business_name = Column(String, nullable=False)
    tax_id = Column(String, nullable=False)
    effective_date = Column(String, nullable=False)
    expiration_date = Column(String, nullable=False)
    liability_limit = Column(Integer, nullable=False)

Base.metadata.create_all(bind=engine)

def save_approved_vendor(data):
    db = SessionLocal()
    try:
        new_vendor = ApprovedVendor(
            legal_business_name=data.legal_business_name,
            tax_id=data.tax_id,
            effective_date=str(data.effective_date),
            expiration_date=str(data.expiration_date),
            liability_limit=data.general_liability_limit
        )
        db.add(new_vendor)
        db.commit()
    except Exception as e:
        st.error(f"Database transaction failed: {e}")
    finally:
        db.close()

# ==========================================
# EMAIL TRANSMISSION LOGIC
# ==========================================
def send_rejection_email_live(vendor_email: str, subject: str, body_content: str) -> bool:
    sender_email = os.getenv("VENDER_BOT_EMAIL", "your_bot_email@gmail.com")
    sender_password = os.getenv("VENDER_BOT_APP_PASSWORD", "your_app_password_here")
    
    if sender_password == "your_app_password_here":
        st.warning("⚠️ SMTP credentials not configured. Email blocked from leaving development environment.")
        return False

    msg = EmailMessage()
    msg.set_content(body_content)
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = vendor_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True
    except Exception as e:
        st.error(f"Failed to transmit email via SMTP: {e}")
        return False

# ==========================================
# AI AGENTS & SCHEMAS 
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

try:
    api_key = st.secrets["OPENAI_API_KEY"]
    model = OpenAIModel('gpt-4o', api_key=api_key)
except Exception:
    st.error("⚠️ OPENAI_API_KEY not found in Streamlit secrets.")
    st.stop()

extraction_agent = Agent(
    model,
    system_prompt=(
        "You are a strict compliance auditor. Read the provided contract text and "
        "extract the exact information required by the schema. Do not guess. "
        "If a required field is completely missing, flag missing_critical_data as True."
    ),
    result_type=VendorComplianceSchema
)

rejection_agent = Agent(
    model,
    system_prompt=(
        "You are a professional legal compliance officer. Write a polite but firm "
        "email to a vendor explaining that their contract cannot be approved yet. "
        "List the exact compliance flags provided to you as bullet points they must fix. "
        "Include placeholders for vendor contact email at the top."
    )
)

chat_agent = Agent(
    model,
    system_prompt=(
        "You are a brilliant legal assistant. Use the provided contract text to answer "
        "the user's questions accurately. If the answer is not in the contract text, "
        "say 'That information is not present in this document.' Do not invent answers."
    )
)

# ==========================================
# RULE ENGINE & UTILS
# ==========================================
def compliance_rule_engine(extracted_data: VendorComplianceSchema) -> dict:
    report = {"passed_all_rules": True, "flags": []}
    if extracted_data.general_liability_limit < 1000000:
        report["passed_all_rules"] = False
        report["flags"].append(f"Liability too low: ${extracted_data.general_liability_limit:,}. Minimum is $1,000,000.")
    if extracted_data.auto_renewal_clause is True:
        report["passed_all_rules"] = False
        report["flags"].append("Auto-renewal clause detected. Requires human override.")
    if extracted_data.termination_notice_days < 30:
        report["passed_all_rules"] = False
        report["flags"].append(f"Termination notice too short: {extracted_data.termination_notice_days} days.")
    return report

def extract_text_from_pdf_upload(uploaded_file) -> str:
    reader = PdfReader(uploaded_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

# ==========================================
# WEB APP INTERFACE
# ==========================================
# We define a custom logout button in the sidebar
if st.sidebar.button("🚪 Secure Logout"):
    del st.session_state["password_correct"]
    st.rerun()

st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to:", ["Audit New Contracts", "Approved Vendors Ledger"])

# --- PAGE 1: BATCH AUDIT DASHBOARD ---
if page == "Audit New Contracts":
    st.title("📦 Enterprise Batch Compliance Auditor")
    st.markdown("Upload multiple vendor contracts simultaneously to run a massive parallel compliance check.")

    if "batch_results" not in st.session_state:
        st.session_state.batch_results = {}
    if "selected_chat_file" not in st.session_state:
        st.session_state.selected_chat_file = None
    if "chat_histories" not in st.session_state:
        st.session_state.chat_histories = {}

    uploaded_files = st.file_uploader("Drag and drop multiple contract PDFs here", type="pdf", accept_multiple_files=True)

    if uploaded_files:
        if st.button("🚀 Execute Batch Process"):
            with st.spinner(f"Processing {len(uploaded_files)} documents through the agent pipelines..."):
                for uploaded_file in uploaded_files:
                    filename = uploaded_file.name
                    if filename not in st.session_state.batch_results:
                        text = extract_text_from_pdf_upload(uploaded_file)
                        result = extraction_agent.run_sync(text)
                        data = result.output
                        report = compliance_rule_engine(data)
                        
                        st.session_state.batch_results[filename] = {
                            "data": data,
                            "report": report,
                            "text": text,
                            "rejection_email": None,
                            "email_sent": False,
                            "status": "Auto-Approved" if report["passed_all_rules"] else "Flagged for Review"
                        }
                        
                        if report["passed_all_rules"]:
                            save_approved_vendor(data)

    if st.session_state.batch_results:
        st.divider()
        st.subheader("📋 Processing Queue Results")
        
        for filename, details in list(st.session_state.batch_results.items()):
            data = details["data"]
            report = details["report"]
            status = details["status"]
            
            if status in ["Auto-Approved", "Manually Approved"]:
                title_string = f"🟢 {filename} — APPROVED"
            elif status == "Rejected":
                title_string = f"🔴 {filename} — REJECTED (Email Sent)" if details.get("email_sent") else f"🔴 {filename} — REJECT