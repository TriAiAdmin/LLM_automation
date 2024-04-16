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
        "model": "gpt-4-vision-preview",
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
        "max_tokens": 300
    }

    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    if response.status_code == 200:
        response_json = response.json()

        raw_json = response_json['choices'][0]['message']['content']
        response_text = raw_json.replace("json", "").replace("```", "").strip()
        try:
            response_data = json.loads(response_text)
            company_code = response_data.get('company_code')
            invoice_type = response_data.get('invoice_type')
            invoice_no = response_data.get('invoice_no')
            po_number = response_data.get('po_number')
            sbu_number = response_data.get('sbu_number')
            invoice_date = response_data.get('invoice_date')
            invoice_amount = response_data.get('invoice_amount')
            invoice_tax_amount = response_data.get('invoice_tax_amount')
            comment = response_data.get('comment')
        except json.JSONDecodeError:
            company_code, invoice_type, invoice_no, po_number, sbu_number,invoice_date, invoice_amount, invoice_tax_amount, comment  = None, None, None, None, None, None, None, None
        return company_code, invoice_type, invoice_no, po_number,sbu_number, invoice_date, invoice_amount, invoice_tax_amount, comment
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
       
        Invoice Type (Non-Tax Invoices, Tax Invoices, or SVAT Invoices),
        Invoice No,
        PO number,
        Invoice Date,
        Invoice Amount,
        Invoice Tax Amount,
        from the image and return the response as a JSON object with
        'sbu',
        'invoice_type',
        'invoice_no',
        'po_number',
        'invoice_date',
        'invoice_amount',
        'invoice_tax_amount',
        'comment'
         as keys.

    must retun json object only no more any text provide
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

    When considering the po number should follow below details:

    1. When PO number name is not mentioned consider these always alternative name for PO number: purchase order number , order number, buyer order number, your order refrence number, PO NO, Customer PO, Cust. PO No, Purchase Ord.No , Purchase, company name Order No and Manual NO.
    2. If there is any value is missing for PO name, Do not match with the address when there is no po number.set it to null only, ensure this all the time, make sure always if PO number is not there do not match it with the address, set it to null only.
    3. When PO number or alternative names for PO number's number count is less then 8 numbers it should set to null, should display in jason as null it's must follow this, ensure this always.
    4. When PO number or alternative names for PO number is null set sbu as null, make sure this always. 
    5. If there is a PO number or in other alternative name it should be 10 digit and if it has 9 digit add 0 before and make it 10 digit, when PO number has 10 digits do not make any changes, make it sure always, ensure this always.
    6. When the PO number has 10 digits don't make any changes in the PO number, make it sure always.
    7. If PO number or it's alternative names are less then 8 digits it should display as null, make sure always when PO number is null sbu should be null. Make sure always result it should show up in the po_number side, make sure this always. 
    8. When PO number first digit is not clear have to match with the address which is below here and arrange the first digit,  
       as per the given range first digit make sure always this rule is for only you found PO Number.
    9. Make sure all the time if PO Name or Other Alternative names doesn't mention in the upload invoice it should be set to null always, make sure always if PO number is null do not match  the address with the sbu, this is must , ensure this output always. 
    11. Always check if the PO number or other alternatives do not meet the criteria in the preferred ranges, and if the PO number or alternative name is less than 9 digits, it should be set as the null in the po number display, when PO number is null sbu should set to null, it's must and ensure it always.
        You should not compare it with the address when there is no PO number or the other alternative name is not there. The sbu should be set to null, make ensure this always.
    12. 
    13. Ranges Should be:
        - If po number between 7100000000 - 7999999999 address will be Ceylon Buiscuit Limited, Makumbura Pannipitiya.
            It's 'sbu' will be C100.
        - If po number between 0041000000 - 0051999999 address will be CBL Food International (PVT) Limited, Ranala.
            It's 'sbu' will be C200.
        - If po number between 0310000001 - 0389999999 address will be Convenience food (PVT) LTD,7th Lane,Off Borupana Road,Kandawala,Ratmalana.
            It's 'sbu' will be C300.
        - If po number between 0400000000 - 0469999999 address will be CBL Plenty foods (PVT) LTD,Sir John Kothalawala Mawatha,Ratmalana.
            It's 'sbu' will be C400.
        - If po number between 5300000000 - 5999999999 address will be CBL Exports (PVT) LTD,Seethawaka Export Processing Zone,Seethawaka.
            It's 'sbu' will be C500.
        - If po number between 0610000000 - 0659999999 address will be CBL Natural Foods (PVT) LTD,Awariwatte Road, Heenetiyana,Minuwangoda.
            It's 'sbu' will be C600.
        - If po number between 1710000001 - 1759999999 address will be CBL Cocos (PVT) LTD,No. 145, Colombo Rd, Alawwa, Alawwa.
            It's 'sbu' will be C700.
        - If po number between 1810000001 - 1869999999 address will be CBL Global Foods (PVT) LTD,Colombo Road, Alawwa.
            It's 'sbu' will be C800.
    14. Ensure the above data thoroughly it's essential always.

    Ensure that all currency values are converted to a standard format ISO 4217, default value LKR, also base on supplier address and supplier phone number.

    Ensure the  Telephone Number is formatted as ISO standard phone number format (e.g., +94123456789).

    The invoice date format should be DD/MM/YYYY, correcting the month to the most recent if unclear but not future-dating.

    'Invoice Amount' and 'Invoice Tax Amount' retun must be with two decimal places.

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
            company_code, invoice_type, invoice_no, po_number,sbu_number, invoice_date, invoice_amount, invoice_tax_amount, comment = get_openai_response(base64_image,prompt)
            if company_code or invoice_type or invoice_no or po_number  or sbu_number or invoice_date or invoice_amount or invoice_tax_amount:
            
                desired_output = {
                    "company_code": company_code,
                    "invoice_type": invoice_type,
                    "invoice_no": invoice_no,
                    "po_number": po_number,
                    "sbu_number":sbu_number,
                    "invoice_date": invoice_date,
                    "invoice_amount": invoice_amount,
                    "invoice_tax_amount": invoice_tax_amount,
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

    time.sleep(5)  # Wait before checking for new files
