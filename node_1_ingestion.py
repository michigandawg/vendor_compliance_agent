from datetime import date
from typing import Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent

# ==========================================
# 1. THE STRICT EXTRACTION SCHEMA (THE GATE)
# ==========================================
class VendorComplianceSchema(BaseModel):
    """
    The rigid digital form the AI must fill out. 
    If the AI hallucinates or uses the wrong format, Pydantic blocks it.
    """
    # Category 1: Identity & Fraud
    legal_business_name: str = Field(..., description="Exact legal name of the vendor entity.")
    tax_id: str = Field(..., description="9-digit EIN or Tax ID (Format: XX-XXXXXXX).")
    
    # Category 2: Timeline & Renewals
    effective_date: date = Field(..., description="The start date of the contract.")
    expiration_date: date = Field(..., description="The end date of the contract.")
    auto_renewal_clause: bool = Field(..., description="True if the contract auto-renews, False if not.")
    termination_notice_days: int = Field(..., description="Number of days notice required to cancel.")
    
    # Category 3: Financial Risk
    total_contract_value: Optional[str] = Field(None, description="Total cost or payment terms (e.g., 'Net 30').")
    general_liability_limit: int = Field(..., description="Max dollar amount of General Liability Insurance.")
    indemnification_cap: Optional[int] = Field(None, description="Maximum dollar amount the vendor can be sued for.")
    
    # Category 4: Regulatory
    data_privacy_flag: bool = Field(..., description="True if the contract involves personal/health data (GDPR/HIPAA).")
    
    # The Gate Trigger
    missing_critical_data: bool = Field(
        default=False,
        description="Set to True ONLY IF any of the required fields above cannot be found in the document."
    )

# ==========================================
# 2. THE AI AGENT CONFIGURATION
# ==========================================
# We initialize the agent to use Gemini 1.5 Flash (fast, cheap, highly accurate for extraction)
extraction_agent = Agent(
    'google-gla:gemini-1.5-flash',
    system_prompt=(
        "You are a strict compliance auditor. Read the provided contract text and "
        "extract the exact information required by the schema. Do not guess or make up data. "
        "If a required field is completely missing, flag missing_critical_data as True."
    ),
    result_type=VendorComplianceSchema
)

# ==========================================
# 3. THE EXECUTION FUNCTION (TESTING THE NODE)
# ==========================================
async def test_node_1(sample_document_text: str):
    """
    Feeds the document to the agent and checks the gate.
    """
    print("Ingesting document...")
    
    # Run the agent. It will strictly format the output to our schema.
    result = await extraction_agent.run(sample_document_text)
    extracted_data = result.data
    
    print("\n--- EXTRACTION RESULTS ---")
    # This prints out the clean, structured data
    print(extracted_data.model_dump_json(indent=2))
    
    # THE APPROVAL GATE LOGIC
    print("\n--- GATE CHECK ---")
    if extracted_data.missing_critical_data:
        print("🛑 GATE FAILED: The document is missing required compliance fields.")
        print("-> Action: Routing to Human Review Queue.")
        # In the next step, we will wire this to pause the state machine and alert you.
    else:
        print("✅ GATE PASSED: All 10 fields successfully extracted.")
        print("-> Action: Proceed to Node 2 (Compliance Rule Auditing).")

# To actually run this test in your terminal, you would execute the async function.
# (We will add the run logic once you confirm the setup).
