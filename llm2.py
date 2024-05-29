import os
import shutil
import io
import base64
import json
import requests
import pandas as pd
from thefuzz import process
from pdf2image import convert_from_path
from PIL import Image
import time
from dotenv import load_dotenv

load_dotenv()

# Directory setup
base_folder = "upload"
os.makedirs(base_folder, exist_ok=True)
in_progress_folder = os.path.join(base_folder, "in_progress")
completed_folder = os.path.join(base_folder, "completed")

# Ensure subdirectories exist
os.makedirs(in_progress_folder, exist_ok=True)
os.makedirs(completed_folder, exist_ok=True)

def encode_image_to_base64(image):
    if image.mode == 'RGBA':
        image = image.convert('RGB')
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def convert_pdf_to_images(pdf_path):
    images = convert_from_path(pdf_path)
    return images

def update_csv(filename, desired_output):
    csv_file_path = "output2.csv"

    desired_output["filename"] = filename

    df = pd.DataFrame([desired_output])

    if os.path.exists(csv_file_path):
        df.to_csv(csv_file_path, mode='a', header=False, index=False)
    else:
        df.to_csv(csv_file_path, index=False)

def get_openai_response(base64_image,prompt):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"
    }
    
    payload = {
        "model": "gpt-4-turbo",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
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
        "max_tokens": 400
    }

    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    if response.status_code == 200:
        response_json = response.json()

        raw_json = response_json['choices'][0]['message']['content']
        response_text = raw_json.replace("json", "").replace("```", "").strip()
        try:
            response_data = json.loads(response_text)
            sbu = response_data.get('sbu')
            invoice_type = response_data.get('invoice_type')
            invoice_no = response_data.get('invoice_no')
            po_number = response_data.get('po_number')
            invoice_date = response_data.get('invoice_date')
            invoice_amount = response_data.get('invoice_amount')
            invoice_tax_amount = response_data.get('invoice_tax_amount')
            delivery_note_number = response_data.get('delivery_note_number')
            comment = response_data.get('comment')
        except json.JSONDecodeError:
            sbu,  delivery_note_number, invoice_no, po_number, invoice_date, invoice_amount, invoice_tax_amount, invoice_type, comment  = None, None, None, None, None, None, None, None, None
        return sbu,  delivery_note_number, invoice_no, po_number, invoice_date, invoice_amount, invoice_tax_amount, invoice_type, comment
    else:
        print(f"Error in OpenAI API response: {response.status_code} - {response.text}")
        return None, None

def find_best_match(name, address, vendor_df):
    name_match = process.extractOne(name, vendor_df['Name of vendor'], score_cutoff=75)
    if name_match:
        potential_matches = vendor_df[vendor_df['Name of vendor'] == name_match[0]]
        address_match = process.extractOne(address, potential_matches['Street'], score_cutoff=75)
        if address_match:
            return potential_matches[potential_matches['Street'] == address_match[0]]['Vendor Code'].iloc[0]
    return None

def process_files(batch_files):
    prompt = '''Extract the following details from the invoice:
        sbu
        Invoice Type (Non-Tax Invoices, Tax Invoices, or SVAT Invoices),
        Invoice No,
        PO number,
        Invoice Date,
        Invoice Amount,
        Invoice Tax Amount,
        Delivery note number,
        from the image and return the response as a JSON object with
        'sbu'
        'invoice_type',
        'invoice_no',
        'po_number',
        'invoice_date',
        'invoice_amount',
        'invoice_tax_amount',
        'delivery_note_number',
        'comment'
         as keys.

    must return json object only no more any text provide


    1.Invoice Type
    When considering the Invoice type should follow below details:

      1.1 For Tax Invoices:
       
        a. VAT Amount > 0 (≠ null)
        b. VAT % > 0 (≠ null)
        c. Subtotal ≠ Invoice Amount

        Consider as a tax invoice if the pair a – b – c is valid.

        

       1.2. For Non-Tax Invoices:
        
        a. VAT amount = 0
        b. VAT % = 0
        c. Subtotal = Invoice Amount

        Consider as a non-tax invoice if the pair a – b – c is valid.

       1.3. For SVAT Invoices:
        a. SVAT % > 0 (≠ null)
        b. SVAT amount > 0 (≠ null)
       
        Consider as a SVAT invoice if a & b is valid 

        alternative names for SVAT are:
            Suspended Vat
            Suspended Tax

    2. PO Number        

    When considering the PO number should follow below details:

    PO numbers typically contain 10 digits.

      2.1. PO number validation
        Extract the accurate PO number from the invoice.
        Consider alternative names such as:
            PO number
            Purchase order number
            Order Number (NO)
            Buyer order number
            Your order reference number
            PO No
            Customer PO
            Cust. PO No
            Manual No
            Order Ref
       
            
       
        Identify the SBU (Strategic Business Unit) based on the PO range once the PO number is extracted.
        Extract the SBU/company name from the address and tag it to the relevant PO category.
    
      2.2. Data Praises:

        The following are the SBU, company name, and PO range information:

            SBU: C100, Company: Ceylon Biscuit Limited, Address: Makumbura, Pannipitiya, PO range: 7100000000 -- 7999999999
            SBU: C200, Company: CBL Food International (PVT) Limited, Address: Ranala, PO range: 0041000000 -- 0051999999
            SBU: C300, Company: Convenience Food (PVT) LTD, Address: Kandawala, Ratmalana, PO range: 0310000001 -- 0389999999
            SBU: C400, Company: CBL Plenty Foods (PVT) LTD, Address: Ratmalana, PO range: 0400000000 -- 0469999999
            SBU: C500, Company: CBL Exports (PVT) LTD, Address: Seethawaka, PO range: 5300000000 - 5999999999
            SBU: C600, Company: CBL Natural Foods (PVT) LTD, Address: Minuwangoda, PO range: 0610000000 -- 0659999999
            SBU: C700, Company: CBL Cocos (PVT) LTD, Address: Alawwa, PO range: 1710000001 - 1759999999
            SBU: C800, Company: CBL Global Foods (PVT) LTD, Address: Alawwa, PO range: 1810000001 -- 1869999999

      2.3. Failure Attributes:

        If the PO number is out of range, data praise the 1st digit according to the SBU PO range.
        If the extracted PO number mismatches the defined PO range even after data praising, mark as "Wrong PO".
        If the PO number has <= 7 digits, mark as "Wrong PO".
        Else, mark as "Wrong PO".
    
      2.4. Ensure the above structure thoroughly it's essential always.

    3. Delivery Note Number Validation
    
    when considering the 'Delivery note number' should follow below details:
    Extract the accurate Delivery note number from the invoice.
        Consider alternative names such as:
            Delivery note number
            Dispatch note number
            DO Number
            AOD
            Delivery order Number
            DN Number
            Advise No
            Delivery note number ≠ Job No
    

    4. Currency
    Ensure that all currency values are converted to a standard format ISO 4217, also base on country of supplier address and country code of supplier phone number, default value LKR.

    
    Ensure the  Telephone Number is formatted as ISO standard phone number format (e.g., +94123456789).

    5. Invoice Date
    The invoice date format should be DD/MM/YYYY, correcting the month to the most recent if unclear but not future-dating.
 
    6. Invoice Amount
    'Invoice Amount' and 'Invoice Tax Amount' retun must be with two decimal places.

    'Invoice Amount' Consider alternative names such as:
        Invoive amount
        Invoice value
        Grand Total	
        Total Amount
        lnvoice Total
        Gross Value

     7. Invoice Number
    'Invoice No' Consider alternative names such as:
        Invoice No
        Invoice number	
        Invoice Ref
        Invoice Reference
        Our reference No
    
    8. VAT Amount
    'VAT Amount' Consider alternative names such as:
        VAT	Tax	
        Tax amount

    9. Sub Total
    'Sub Total' Consider alternative names such as:
        Net total
        Total	
        Total amount	
        Amount	
        Balance/ amount due	
        Invoice value  
        Sub Total ≠ Gross Total

General Rules
If any value is missing, set it to null only.

If any detail is unclear or not sure, please specify an error as an 'comment' in the JSON object. If no error is found, set it to Null.
    '''
    for file_name in batch_files:
        src_path = os.path.join(base_folder, file_name)
        in_progress_path = os.path.join(in_progress_folder, file_name)
        shutil.move(src_path, in_progress_path)

        images = []
        if file_name.endswith(".pdf"):
            images = convert_pdf_to_images(in_progress_path)
        elif file_name.endswith((".png", ".jpg", ".jpeg")):
            images = [Image.open(in_progress_path)]

        for image in images:
            base64_image = encode_image_to_base64(image)
            sbu, invoice_type, invoice_no, po_number, invoice_date, invoice_amount, invoice_tax_amount, delivery_note_number, comment = get_openai_response(base64_image,prompt)
            if sbu or invoice_type or invoice_no or po_number  or invoice_date or invoice_amount or invoice_tax_amount or delivery_note_number:
            
                desired_output = {
                    "sbu": sbu,
                    "invoice_type": invoice_type,
                    "invoice_no": invoice_no,
                    "po_number": po_number,
                    "invoice_date": invoice_date,
                    "invoice_amount": invoice_amount,
                    "invoice_tax_amount": invoice_tax_amount,
                    "delivery_note_number": delivery_note_number,
                    "comment": comment,
                    "filename": None
                }
                formatted_json = json.dumps(desired_output, indent=4)
                print(formatted_json)
                update_csv(file_name, desired_output)
                completed_path = os.path.join(completed_folder, file_name)
                shutil.move(in_progress_path, completed_path)
            else:
                print(f"Failed to extract details from {file_name}")

        

while True:
    all_files = [f for f in os.listdir(base_folder) if os.path.isfile(os.path.join(base_folder, f))]
    batch_files = [f for f in all_files if f.endswith(('.pdf', '.png', '.jpg', '.jpeg'))]

    if batch_files:
        process_files(batch_files)

    time.sleep(8)  # Wait before checking for new files
