# System Specification: Automated Invoice QR Code Generator

This document outlines the technical specification for a serverless application that ingests emails with PDF invoices, extracts payment details using an OpenAI LLM, generates a Belgian EPC-compliant QR code, and replies to the sender with the ready-to-scan code.

---

## 1. System Overview

An asynchronous, event-driven serverless function acting as a webhook receiver for inbound emails. The application is entirely stateless and executes only when triggered by an incoming email payload from the Resend API.

## 2. Infrastructure & Environment

* **Platform:** Scaleway Serverless Functions
* **Runtime:** Python 3.11+
* **Memory Limit:** 256 MB RAM
* **Timeout:** 10 seconds
* **Trigger:** HTTP POST request (Inbound Webhook from Resend)

## 3. Environment Variables

The function requires the following secure environment variables configured in the Scaleway console:

* `RESEND_API_KEY`: API key for sending outbound emails.
* `OPENAI_API_KEY`: API key for accessing the OpenAI API.
* `COMPANY_NAME`: The name of the beneficiary to be encoded in the QR code (e.g., "Jane Doe" or "Acme Corp").

## 4. Dependencies

The `requirements.txt` file must contain the following packages:

* `resend`: Official Resend Python SDK for email dispatch.
* `pypdf`: Pure-Python library for fast, serverless-friendly PDF text extraction.
* `openai`: Official OpenAI SDK for LLM interactions.
* `segno`: Pure-Python library for generating the EPC QR code.

## 5. Data Flow & Component Logic

### Step 1: Webhook Ingestion

The function receives an HTTP POST request triggered by Resend. It parses the JSON body to extract the `From` email address (the original sender) and the `Attachments` array. If no PDF attachment is found, it immediately returns a `200 OK` to prevent webhook retries.

### Step 2: PDF Text Extraction

The base64-encoded PDF from the Resend payload is decoded into bytes. `pypdf` reads the in-memory byte stream, iterating through all pages to concatenate the raw text into a single string.

### Step 3: LLM Data Extraction

The raw text is sent to OpenAI's `gpt-5.4-mini` model. The prompt uses strict system instructions and the `json_object` response format to guarantee the return of a clean JSON object containing three exact keys: `amount`, `iban`, and `communication`.

### Step 4: EPC QR Code Generation

The extracted JSON data is formatted into the strict European Payments Council (EPC) string format required for Belgian bank transfers. `segno` generates a QR code from this string and saves it as a PNG into a virtual memory buffer. This PNG is then base64-encoded.

### Step 5: Email Dispatch

The application constructs a new email payload using the Resend SDK. It addresses the reply to the original sender, attaches the base64-encoded QR code PNG, and dispatches the email.

---

## 6. Complete Code Implementation (`handler.py`)

```python
import json
import base64
import io
import os
import resend
from openai import OpenAI
from pypdf import PdfReader
import segno

# Initialize API clients from environment variables
resend.api_key = os.environ.get("RESEND_API_KEY")
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def extract_pdf_text(base64_pdf):
    """Decodes the base64 PDF and extracts raw text."""
    pdf_bytes = base64.b64decode(base64_pdf)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def extract_details_via_llm(raw_text):
    """Passes raw text to OpenAI to extract structured payment data."""
    prompt = f"""
    Extract the total amount, Belgian IBAN, and payment communication from this invoice.
    Return ONLY a JSON object with the keys: 
    - 'amount' (string, e.g. "50.00", no currency symbols)
    - 'iban' (string without spaces)
    - 'communication' (string)
    
    Invoice text: {raw_text}
    """
    
    response = openai_client.chat.completions.create(
        model="gpt-5.4-mini",
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": "You are a precise data extraction assistant designed to output strict JSON."},
            {"role": "user", "content": prompt}
        ]
    )
    
    return json.loads(response.choices[0].message.content)

def generate_qr_base64(payment_data):
    """Generates an EPC-compliant QR code and returns it as a base64 string."""
    name = os.environ.get("COMPANY_NAME", "Recipient Name") 
    
    # Construct strict EPC string
    epc_data = (
        f"BCD\n"
        f"002\n"
        f"1\n"
        f"SCT\n\n"
        f"{name}\n"
        f"{payment_data['iban']}\n\n"
        f"EUR{payment_data['amount']}\n\n"
        f"{payment_data['communication']}\n"
    )
    
    qr = segno.make(epc_data, error='M')
    buffer = io.BytesIO()
    qr.save(buffer, kind='png', scale=5)
    
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def handle(event, context):
    """
    Scaleway Serverless entry point.
    Expects an event dict containing the HTTP request body.
    """
    try:
        # 1. Parse Inbound Webhook payload
        body = json.loads(event.get("body", "{}"))
        sender_email = body.get("From")
        attachments = body.get("Attachments", [])
        
        if not attachments:
            return {"statusCode": 200, "body": "No attachments found. Exiting cleanly."}
            
        # Extract the first attachment
        pdf_content = attachments[0].get("Content") 
        
        # 2. Extract Text from PDF
        raw_text = extract_pdf_text(pdf_content)
        
        # 3. Extract JSON Data via LLM
        payment_data = extract_details_via_llm(raw_text)
        
        # 4. Generate QR Code Image
        qr_base64 = generate_qr_base64(payment_data)
        
        # 5. Dispatch Reply Email via Resend
        email_params = {
            "from": "pay@yourdomain.com",  # Replace with your verified Resend domain
            "to": sender_email,
            "subject": "Your Payment QR Code",
            "html": "<p>Scan the attached QR code with your Belgian banking app or Payconiq to complete the payment.</p>",
            "attachments": [
                {"filename": "payment_qr.png", "content": qr_base64}
            ]
        }
        resend.Emails.send(email_params)

        return {"statusCode": 200, "body": "Success: QR code generated and sent."}

    except Exception as e:
        # Log error but return 200 to prevent the webhook provider from endlessly retrying
        print(f"Execution Error: {e}")
        return {"statusCode": 200, "body": f"Processed with error: {str(e)}"}

```
