from dotenv import load_dotenv
import streamlit as st
import os
import json
from PIL import Image
import pandas as pd
import base64
import requests
import io
import fitz
from pathlib import Path


def ensure_directory_exists(directory_path):
    Path(directory_path).mkdir(parents=True, exist_ok=True)

# Load environment variables
load_dotenv()

def pdf_to_image_mupdf(uploaded_file):
    # Use PyMuPDF to convert the first page of the PDF to an image
    doc = fitz.open(stream=uploaded_file.getvalue(), filetype="pdf")
    page = doc.load_page(0)  # Only converting the first page
    pix = page.get_pixmap()
    img_data = pix.tobytes("ppm")
    image = Image.open(io.BytesIO(img_data))
    return image

def encode_image(image_data):
    if isinstance(image_data, str):  # If path to image file is provided
        with open(image_data, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    elif isinstance(image_data, bytes):  # If image data is provided directly
        return base64.b64encode(image_data).decode('utf-8')
    elif hasattr(image_data, 'tobytes'):  # If PIL Image object is provided
        with io.BytesIO() as buffer:
            image_data.save(buffer, format="JPEG")
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
    else:
        raise ValueError("Invalid image data provided.")

ensure_directory_exists('uploaded_files/')
ensure_directory_exists('static/')

def get_openai_response(user_input, base64_image,):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"
    }

    payload = {
        "model": "gpt-4-vision-preview",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_input
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 300
    }

    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    responseJosn = response.json()
     
    raw_json = responseJosn['choices'][0]['message']['content']
    cleaned_json = raw_json.replace("json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned_json)
    except json.JSONDecodeError as e:
        print(f"Failed to decode JSON from the model response: {e}")
        return {}


def input_image_details(uploaded_file):
    if uploaded_file is not None:
        bytes_data = uploaded_file.getvalue()
        return [{"mime_type": uploaded_file.type, "data": bytes_data}]
    else:
        raise FileNotFoundError("No file uploaded")

def save_uploaded_file(uploaded_file):
    directory = "uploaded_files"
    try:
        if not os.path.exists(directory):
            os.makedirs(directory)
        file_path = os.path.join(directory, uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return True
    except Exception as e:
        print(f"Failed to save file: {e}")
        return False

def update_csv(filename, details):
    new_row_df = pd.DataFrame([{**details, 'filename': filename}])
    new_row_df.to_csv('data.csv', mode='a', index=False, header=not pd.read_csv('data.csv').shape[0])

# Streamlit app setup
st.set_page_config(page_title="Invoice Extractor")
logo_path = "cbl.png"
st.image(logo_path, width=100)
st.header("CBL Invoice Automation App")


uploaded_file = st.file_uploader("Choose an image of the invoice...", type=["jpg", "jpeg", "png", 'pdf'])


input_prompt ='''
You going to act as a OCR.Extract the following details from the invoice:

- Invoice Type (Non-Tax Invoices, Tax Invoices, or SVAT Invoices)
- Supplier Name
- Supplier Address
- Supplier Telephone Number (formatted as ISO standard phone number format)
- Supplier Email
- Supplier Website
- Company VAT No (also can be Customer VAT Registration Number)
- Company SVAT No (also can be Susspended tax Number)
- Company Business Reg. No
- Invoice No
- PO Number (must be in number format only, don't get BPO Number,)
- SBU (SBU number should display) 
- Invoice Date (formatted as DD/MM/YYYY)
- Currency
- Total Value (formatted as a number, also can be sub total/amount or items total/amount)
- Total VAT (formatted as a number)
- Total Invoice Amount (formatted as a number also can be grand total)

If any value is missing, set it to null only.


When considering the po number should follow below details:

1. If there is any value is missing for PO number name, Do not match with the address when there is no po number.set it to null only.
2. If there is a PO number or in other alternative name it should be 10 digit and if it less than 10 add 0 before it till it become 10 digit.
3. When PO number name is not mentioned consider these always alternative name for PO number: purchase order number , order number, buyer order number, your order refrence number, PO NO, Customer PO, Cust. PO No, Purchase Ord.No , Purchase and Manual NO.
4. Extract the exact numbers in the invoices which is relevent to the given name.

5. When PO number first digit is not clear have to match with the address which is belowed here and arrange the first digit.  
   as per the given range first digit.
6. Ranges Should be:
    - If po number between 7100000000 - 7999999999 address will be Ceylon Buiscuit Limited, Makumbura Pannipitiya.
        It's SBU will be C100.
    - If po number between 0041000000 - 0051999999 address will be CBL Food International (PVT) Limited, Ranala.
        It's SBU will be C200.
    - If po number between 0310000001 - 0389999999 address will be Convenience food (PVT) LTD,7th Lane,Off Borupana Road,Kandawala,Ratmalana.
        It's SBU will be C300.
    - If po number between 0400000000 - 0469999999 address will be CBL Plenty foods (PVT) LTD,Sir John Kothalawala Mawatha,Ratmalana.
        It's SBU will be C400.
    - If po number between 5300000000 - 5999999999 address will be CBL Exports (PVT) LTD,Seethawaka Export Processing Zone,Seethawaka.
        It's SBU will be C500.
    - If po number between 0610000000 - 0659999999 address will be CBL Natural Foods (PVT) LTD,Awariwatte Road, Heenetiyana,Minuwangoda.
        It's SBU will be C600.
    - If po number between 1710000001 - 1759999999 address will be CBL Cocos (PVT) LTD,No. 145, Colombo Rd, Alawwa, Alawwa.
        It's SBU will be C700.
    - If po number between 1810000001 - 1869999999 address will be CBL Global Foods (PVT) LTD,Colombo Road, Alawwa.
        It's SBU will be C700.
7. When PO number not in above range it should identify as a wrong PO.

When considering the Invoice type should follow below details:

1. For Tax Invoices:
   a. Tax Invoice as the header
   b. Words like VAT/TAX present in the invoice
   c. VAT Amount > 0 (≠ null)
   d VAT % > 0 (≠ null)
   e. Subtotal ≠ Invoice Amount

   Consider as a tax invoice if the pair c – d – e is valid.

2. For Non-Tax Invoices:
   a Should come without the headings Tax Invoices sans Tax. VAT – but some invoices come with those words where they should be treated as Non-tax and the later T=0 code will be applied after correct identification with SAP integration
   b VAT amount = 0
   c VAT % = 0
   d Subtotal = Invoice Amount

   Consider as a non-tax invoice if the pair b – c – d is valid.

3. For SVAT Invoices:
   a. Words like SVAT mentioned in the invoice
   b. SVAT %
   c. SVAT amount
   d. Suspended VAT
   c. Total amount

   Logic to recognize if this is an SVAT:
   - C (VAT Amount) is not null
   - B (VAT %) is not null

Ensure that all currency values are converted to a standard format ISO 4217, default value LKR.

Ensure the  Telephone Number is formatted as ISO standard phone number format (e.g., +94123456789).

Attempt to calculate it based on the uploaded invoice image.

Supplier data only get from the invoice.

All text content, including headers and footers, must be successfully captured.

Please provide these details as a JSON object only.

The invoice date format should be DD/MM/YYYY, correcting the month to the most recent if unclear but not future-dating.

If any detail is unclear or not sure, please specify an error as an Error Note in the JSON object. If no error is found, set it to Null.
'''

if uploaded_file is not None:
    if uploaded_file.type == "application/pdf":
        st.warning("PDF file detected. Converting to image...")
        image = pdf_to_image_mupdf(uploaded_file)
        encoded_image = encode_image(image)
    else:
        image = Image.open(uploaded_file)
        uploaded_image_path = "uploaded_files/" + uploaded_file.name
        image.save(uploaded_image_path)  # Save the image
        encoded_image = encode_image(uploaded_image_path)

    st.image(image, caption="Uploaded Image.", use_column_width=True)
    
    if save_uploaded_file(uploaded_file):
        st.success("File saved successfully.")
        image_data = input_image_details(uploaded_file)
        response_details = get_openai_response(input_prompt, encoded_image)

        if response_details:
            st.json(response_details)  # Display the JSON response
            update_csv(uploaded_file.name, response_details)
        else:
            st.error("Failed to extract details from the invoice.")
    else:
        st.error("Failed to save the file.")

# Optional: Hide Streamlit style (you might want to adjust or remove this part)
hide_streamlit_style = """
    <style>
        [data-testid="stToolbar"] {visibility: hidden;}
        .reportview-container {
            margin-top:-2rem;
        }
        MainMenu {visibility: hidden;}
        .stDeployButton {display:none;}
        #stDecoration {display: none;}
        footer {visibility: hidden;}
        div.embeddedAppMetaInfoBar_container__DxxL1{visibility: hidden;}
        header {visibility: hidden;}
    </style>
"""
# st.markdown(hide_streamlit_style, unsafe_allow_html=True)