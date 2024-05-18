import os
import shutil
import io
import base64
import json
import requests
import pandas as pd
from thefuzz import process
from pdf2image import convert_from_bytes
from PIL import Image
import time
from dotenv import load_dotenv
import csv
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from azure.core.exceptions import HttpResponseError

load_dotenv()

# Azure setup
connect_str = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
blob_service_client = BlobServiceClient.from_connection_string(connect_str)
input_container_name = 'upload'
in_progress_container_name = 'in-progress'
completed_container_name = 'completed'
output_container_name = 'output'

# Ensure containers exist (create if they don't)
input_container_client = blob_service_client.get_container_client(input_container_name)
in_progress_container_client = blob_service_client.get_container_client(in_progress_container_name)
completed_container_client = blob_service_client.get_container_client(completed_container_name)
output_container_client = blob_service_client.get_container_client(output_container_name)

for container_client in [input_container_client, in_progress_container_client, completed_container_client, output_container_client]:
    try:
        if not container_client.exists():
            blob_service_client.create_container(container_client.container_name)
    except HttpResponseError as e:  # Use the imported HttpResponseError directly
        print(f"An error occurred: {e.message}")

vendor_master_path = "vendor_master.csv"
vendor_master = pd.read_csv(vendor_master_path)
vendor_master['Name of vendor'] = vendor_master['Name of vendor'].str.lower()
vendor_master['Street'] = vendor_master['Street'].str.lower()

def encode_image_to_base64(image):
    if image.mode == 'RGBA':
        image = image.convert('RGB')
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def convert_pdf_to_images(pdf_bytes):
    images = convert_from_bytes(pdf_bytes)
    return images

def find_best_match(name, address, vendor_df):
    name_match = process.extractOne(name, vendor_df['Name of vendor'], score_cutoff=75)
    if name_match:
        potential_matches = vendor_df[vendor_df['Name of vendor'] == name_match[0]]
        address_match = process.extractOne(address, potential_matches['Street'], score_cutoff=75)
        if address_match:
            return potential_matches[potential_matches['Street'] == address_match[0]]['Vendor Code'].iloc[0]
    return None

def update_csv(desired_output):
    csv_file_path = "output.csv"
    fieldnames = list(desired_output.keys())

    if not os.path.exists(csv_file_path):
        with open(csv_file_path, mode='w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
    
    with open(csv_file_path, mode='a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writerow(desired_output)

def update_csv_in_azure(desired_output):
    csv_blob_name = 'output.csv'
    blob_client = blob_service_client.get_blob_client(container=output_container_name, blob=csv_blob_name)

    # Check if the CSV blob exists and download its content if it does
    csv_data = ''
    if blob_client.exists():
        downloader = blob_client.download_blob()
        csv_data = downloader.readall().decode('utf-8')
    
    # Use StringIO to simulate a file for csv.DictWriter
    csv_file = io.StringIO(csv_data)
    writer = csv.DictWriter(csv_file, fieldnames=list(desired_output.keys()))
    
    # If the CSV file is empty, write the header
    if not csv_data:
        writer.writeheader()
    
    # Write the new data row
    writer.writerow(desired_output)

    # Upload the updated CSV data to the blob
    blob_client.upload_blob(csv_file.getvalue(), overwrite=True)


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
            supplier_name = response_data.get('supplier_name')
            supplier_address = response_data.get('supplier_address')
            supplier_telephone = response_data.get('supplier_telephone')
            supplier_email = response_data.get('supplier_email')
            supplier_website = response_data.get('supplier_website')
            supplier_vat_reg_no = response_data.get('supplier_vat_reg_no')
            supplier_svat_reg_no = response_data.get('supplier_svat_reg_no')
            supplier_business_reg_no = response_data.get('supplier_business_reg_no')
            po_number = response_data.get('po_number')
            delivery_note_number = response_data.get('delivery_note_number')
            invoice_date = response_data.get('invoice_date')
            currency = response_data.get('currency')
            invoice_amount = response_data.get('invoice_amount')
            invoice_tax_amount = response_data.get('invoice_tax_amount')
            comment = response_data.get('comment')
        except json.JSONDecodeError:
            company_code, invoice_type, invoice_no, supplier_name, supplier_address, supplier_telephone, supplier_email, supplier_website, supplier_vat_reg_no, supplier_svat_reg_no, supplier_business_reg_no, po_number, delivery_note_number, invoice_date, currency, invoice_amount, invoice_tax_amount, comment  = None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None
        
        response_data = {
            "company_code": company_code,
            "invoice_type": invoice_type,
            "invoice_no": invoice_no,
            "supplier_name": supplier_name,
            "supplier_address": supplier_address,
            "supplier_telephone": supplier_telephone,
            "supplier_email": supplier_email,
            "supplier_website": supplier_website,
            "supplier_vat_reg_no": supplier_vat_reg_no,
            "supplier_svat_reg_no": supplier_svat_reg_no,
            "supplier_business_reg_no": supplier_business_reg_no,
            "po_number": po_number,
            "delivery_note_number": delivery_note_number,
            "invoice_date": invoice_date,
            "currency": currency,
            "invoice_amount": invoice_amount,
            "invoice_tax_amount": invoice_tax_amount,
            "vendor_code": None,
            "comment": comment,
            "filename": None
        }
        return response_data
    else:
        print(f"Error in OpenAI API response: {response.status_code} - {response.text}")
        return None, None

def process_files(batch_blobs):
    prompt = '''Extract the following details from the invoice:
        Company Code
        Invoice Type (Non-Tax Invoices, Tax Invoices, or SVAT Invoices),
        Invoice No,
        Supplier Name,
        Supplier Address,
        Supplier Telephone Number (formatted as ISO standard phone number format),
        Supplier Email,
        Supplier Website,
        Supplier Company VAT Reg No,
        Supplier Company SVAT Reg No,
        Supplier Company Business Reg. No,
        PO number,
        Delivery Note Number,
        Invoice Date,
        Currency,
        Invoice Amount,
        Invoice Tax Amount,
        from the image and return the response as a JSON object with
        'company_code'
        'invoice_type',
        'invoice_no',
        'supplier_name', 
        'supplier_address',
        'supplier_telephone',
        'supplier_email',
        'supplier_website',
        'supplier_vat_reg_no',
        'supplier_svat_reg_no',
        'supplier_business_reg_no',
        'po_number',
        'delivery_note_number',
        'invoice_date',
        'currency',
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

    1. If there is any value is missing for PO number name, Do not match with the address when there is no po number.set it to null only.
    2. If there is a PO number or in other alternative name it should be 10 digit and if it less than 10 add 0 before it till it become 10 digit.
    3. When PO number name is not mentioned consider these always alternative name for PO number: purchase order number , order number, buyer order number, your order refrence number, PO NO, Customer PO, Cust. PO No, Purchase Ord.No , Purchase and Manual NO.
    4. Extract the exact numbers in the invoices which is relevent to the given name.

    5. When PO number first digit is not clear have to match with the address which is belowed here and arrange the first digit.  
    as per the given range first digit.
    6. Ranges Should be:
        - If po number between 7100000000 - 7999999999 address will be Ceylon Buiscuit Limited, Makumbura Pannipitiya.
            It's 'company_code' will be C100.
        - If po number between 0041000000 - 0051999999 address will be CBL Food International (PVT) Limited, Ranala.
            It's 'company_code' will be C200.
        - If po number between 0310000001 - 0389999999 address will be Convenience food (PVT) LTD,7th Lane,Off Borupana Road,Kandawala,Ratmalana.
            It's 'company_code' will be C300.
        - If po number between 0400000000 - 0469999999 address will be CBL Plenty foods (PVT) LTD,Sir John Kothalawala Mawatha,Ratmalana.
            It's 'company_code' will be C400.
        - If po number between 5300000000 - 5999999999 address will be CBL Exports (PVT) LTD,Seethawaka Export Processing Zone,Seethawaka.
            It's 'company_code' will be C500.
        - If po number between 0610000000 - 0659999999 address will be CBL Natural Foods (PVT) LTD,Awariwatte Road, Heenetiyana,Minuwangoda.
            It's 'company_code' will be C600.
        - If po number between 1710000001 - 1759999999 address will be CBL Cocos (PVT) LTD,No. 145, Colombo Rd, Alawwa, Alawwa.
            It's 'company_code' will be C700.
        - If po number between 1810000001 - 1869999999 address will be CBL Global Foods (PVT) LTD,Colombo Road, Alawwa.
            It's 'company_code' will be C700.
    7. When PO number not in above range it should identify as a wrong PO.

    Ensure that all currency values are converted to a standard format ISO 4217, default value LKR, also base on supplier address and supplier phone number.

    Ensure the  Telephone Number is formatted as ISO standard phone number format (e.g., +94123456789).

    The invoice date format should be DD/MM/YYYY, correcting the month to the most recent if unclear but not future-dating.

    If any value is missing, set it to null only.

    If any detail is unclear or not sure, please specify an error as an 'comment' in the JSON object. If no error is found, set it to Null.
    '''
    for blob_name in batch_blobs:
        input_blob_client = input_container_client.get_blob_client(blob_name)
        in_progress_blob_client = in_progress_container_client.get_blob_client(blob_name)
        completed_blob_client = completed_container_client.get_blob_client(blob_name)

        # Move to in-progress
        blob_data = input_blob_client.download_blob().readall()
        in_progress_blob_client.upload_blob(blob_data, overwrite=True)
        input_blob_client.delete_blob()

        images = []
        if blob_name.endswith(".pdf"):
            images = convert_pdf_to_images(blob_data)
        elif blob_name.endswith((".png", ".jpg", ".jpeg")):
            images = [Image.open(io.BytesIO(blob_data))]

        for image in images:
            base64_image = encode_image_to_base64(image)
            response_data = get_openai_response(base64_image,prompt)
            if response_data:
                supplier_name = response_data.get('supplier_name', '').lower()
                supplier_address = response_data.get('supplier_address', '').lower()
                vendor_code = find_best_match(supplier_name, supplier_address, vendor_master)
                response_data["vendor_code"] = vendor_code
                response_data["filename"] = blob_name

                formatted_json = json.dumps(response_data, indent=4)
                print(formatted_json)

                update_csv_in_azure(response_data)

                completed_blob_client.upload_blob(blob_data, overwrite=True)
                in_progress_blob_client.delete_blob()
            else:
                print(f"Failed to extract details {blob_name}")

# Main loop
while True:
    # List blobs in the input container
    all_blobs = input_container_client.list_blobs()
    batch_blobs = [blob.name for blob in all_blobs if blob.name.endswith(('.pdf', '.png', '.jpg', '.jpeg'))]

    if batch_blobs:
        process_files(batch_blobs)

    time.sleep(5)  # Wait before checking for new files
