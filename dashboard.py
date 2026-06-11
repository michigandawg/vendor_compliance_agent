import os
import sqlite3
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

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Vendor Compliance Hub", layout="wide")

# ==========================================
# DATABASE & EMAIL LOGIC
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

def send_rejection_email_live(vendor_email: str, subject: str, body_content: str) -> bool:
    """Sends the drafted email using standard SMTP (e.g., Gmail App Password)."""
    sender_email = os.getenv("VENDER_BOT_EMAIL", "your_bot_email@gmail.com")
    sender_password = os.getenv("VENDER_BOT_APP_PASSWORD", "your_app_password_here")
    
    if sender_password == "your_app_password_here":
        st.warning("⚠️ SMTP credentials not configured. Update sender_password in the code to test live sending.")
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

setup_database()

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

model = OpenAIModel('gpt-4o')

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
                title_string = f"🔴 {filename} — REJECTED (Email Sent)" if details.get("email_sent") else f"🔴 {filename} — REJECTED (Drafted)"
            else:
                title_string = f"🟡 {filename} — ACTION REQUIRED"
                
            with st.expander(title_string, expanded=(status == "Flagged for Review")):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**Extracted Registry Structure**")
                    st.json(data.model_dump())
                    
                with col2:
                    st.markdown("**Compliance System Signals**")
                    if "Approved" in status:
                        st.success("All compliance parameters passed perfectly. Document archived.")
                    elif status == "Rejected":
                        st.error("Application rejected and notification processed.")
                    else:
                        for flag in report["flags"]:
                            st.warning(flag)
                        
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("Approve Override", key=f"app_{filename}"):
                                save_approved_vendor(data)
                                st.session_state.batch_results[filename]["status"] = "Manually Approved"
                                st.rerun()
                        with c2:
                            if st.button("Issue Rejection", key=f"rej_{filename}"):
                                flags_text = "\n".join(report["flags"])
                                prompt = f"Draft an email for {data.legal_business_name}. Vendor Email Placeholder: [Insert Vendor Representative Email Here]. Here are the flags:\n{flags_text}"
                                rej_result = rejection_agent.run_sync(prompt)
                                st.session_state.batch_results[filename]["rejection_email"] = rej_result.output
                                st.session_state.batch_results[filename]["status"] = "Rejected"
                                st.rerun()

                if details["rejection_email"] and not details.get("email_sent"):
                    st.divider()
                    st.markdown("**Automated Rejection Correspondence**")
                    
                    edited_email = st.text_area("Review and edit correspondence draft:", details["rejection_email"], height=220, key=f"email_box_{filename}")
                    
                    vendor_dest_email = st.text_input("Target Vendor Representative Email:", "vendor_rep@supplier.com", key=f"email_to_{filename}")
                    
                    if st.button("✉️ Send Email to Vendor Live", key=f"send_btn_{filename}"):
                        with st.spinner("Transmitting email over secure SMTP channel..."):
                            subject_line = f"Contract Compliance Review: {data.legal_business_name}"
                            if send_rejection_email_live(vendor_dest_email, subject_line, edited_email):
                                st.session_state.batch_results[filename]["email_sent"] = True
                                st.success("Email successfully transmitted to recipient!")
                                st.rerun()
                            else:
                                st.error("Failed to transmit. Please verify SMTP app credentials in code.")

        st.divider()
        st.subheader("🕵️‍♂️ Interactive Investigation Desk")
        
        chat_file = st.selectbox(
            "Select an uploaded contract to interrogate:", 
            options=list(st.session_state.batch_results.keys())
        )
        
        if chat_file:
            st.session_state.selected_chat_file = chat_file
            if chat_file not in st.session_state.chat_histories:
                st.session_state.chat_histories[chat_file] = []
                
            for msg in st.session_state.chat_histories[chat_file]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            if user_question := st.chat_input("Ask a question about the selected document:", key="batch_chat_input"):
                st.session_state.chat_histories[chat_file].append({"role": "user", "content": user_question})
                st.rerun()

if page == "Audit New Contracts" and st.session_state.get("selected_chat_file"):
    current_file = st.session_state.selected_chat_file
    if st.session_state.chat_histories[current_file] and st.session_state.chat_histories[current_file][-1]["role"] == "user":
        latest_question = st.session_state.chat_histories[current_file][-1]["content"]
        raw_doc_text = st.session_state.batch_results[current_file]["text"]
        
        context_prompt = f"Contract Text:\n{raw_doc_text}\n\nUser Question:\n{latest_question}"
        chat_result = chat_agent.run_sync(context_prompt)
        
        st.session_state.chat_histories[current_file].append({"role": "assistant", "content": chat_result.output})
        st.rerun()

elif page == "Approved Vendors Ledger":
    st.title("🏢 Secure Vendor Ledger")
    st.markdown("Below is the live database of all vendors that have passed compliance or received a human override.")
    
    conn = sqlite3.connect('vendor_compliance.db')
    try:
        df = pd.read_sql_query("SELECT * FROM approved_vendors", conn)
        if df.empty:
            st.info("No vendors have been approved yet.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Error loading database: {e}")
    finally:
        conn.close()