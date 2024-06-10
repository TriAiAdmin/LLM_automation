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


def convert_string_to_amount(value):
    try:
        converted_value = value.replace('\s', '').replace(',', '')
        return float(converted_value)
    except:
        return 0


def convert_po_num_to_list(po_num):
    validated_po_num = []
    if (po_num == "null") or (po_num == "") or (po_num is None):
        po_num = [""]
    
    if type(po_num) is not list:
        po_num = [po_num]

    for i in po_num:
        if len(i)==10: validated_po_num.append(i)
        else: validated_po_num.append('wrong po')

    return validated_po_num


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
        # print(response_text)
        try:
            response_data = json.loads(response_text)

            invoice_date = response_data.get('invoice_date')
            currency = response_data.get('currency')
            po_number = response_data.get('po_number')
            
            suspended_tax_amount = response_data.get('suspended_tax_amount')
            vat_amount = response_data.get('vat_amount')
            delivery_note_number = response_data.get('delivery_note_number')
            
            invoice_amount = response_data.get('invoice_amount')
            invoice_no = response_data.get('invoice_no')
            sub_total = response_data.get('sub_total')
            
        except json.JSONDecodeError as e:
            print(e)
            (
                invoice_date, currency, po_number,
                suspended_tax_amount, vat_amount, delivery_note_number,
                invoice_amount, invoice_no, sub_total,
            )  = (
                None, None, None, 
                None, None, None, 
                None, None, None, 
            )
        return (
                invoice_date, currency, po_number,
                suspended_tax_amount, vat_amount, delivery_note_number,
                invoice_amount, invoice_no, sub_total,
            )
    else:
        print(f"Error in OpenAI API response: {response.status_code} - {response.text}")
        return (
                None, None, None, 
                None, None, None, 
                None, None, None, 
            )


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
        Invoice Date,
        Currency Type,
        PO Number,
        Suspended Tax Amount,
        Vat Amount,
        Delivery Note Number Validation,
        Invoice Amount,
        Invoice Number,
        Sub Total
        from the image and return the response as a JSON object with
        'invoice_date'
        'currency',
        'po_number',
        'suspended_tax_amount',
        'vat_amount',
        'delivery_note_number',
        'invoice_amount',
        'invoice_no',
        'sub_total',
         as keys.

    must return json object only no more any text provide

    1. Invoice Date
        Extract the accurate Invoice Date from the invoice.
    
        Consider alternative names such as:
            Date
            Invoice Date
    
        Invoice Date that could be in various formats such as: 
            10/24/2024, 
            Oct/24/2024, 
            24/10/2024, 
            24/Oct/2024.             
        convert it to a uniform format DD/MM/YYYY.
    
    2. Currency Type
        I need to extract the standard currency type used in these invoices. Here's the process to follow:
        1. **Direct Currency Extraction**:
           - Search for common currency symbols (e.g., $, €, £) or currency codes (e.g., USD, EUR, GBP) within the text of the PDF.
           - If a currency is mentioned, extract it as the standard currency type.

        2. **Currency Inference from Country**:
           - If no currency is mentioned in the invoice, check for the presence of a country name in the address section.
           - Use the country name to infer the currency type. For example, if the country is "United States," the currency should be USD; if the country is "Germany," the currency should be EUR, etc.

        3. **Default Currency**:
           - If neither currency nor country is mentioned in the invoice, default the standard currency type to LKR (Sri Lankan Rupee).

        Consider the following example country-to-currency mappings:
            - United States -> USD
            - Eurozone countries (Germany, France, etc.) -> EUR
            - United Kingdom -> GBP
            - Australia -> AUD
            - Canada -> CAD
            - India -> INR
            - Japan -> JPY
            - Default -> LKR
        
        Also, include any additional steps or checks that might be useful for ensuring accurate extraction and inference.

    3. PO Number
    
        There could be multiple "PO Numbers".
        
        3.1 In the invoices, "PO Number" can be mentioned using various alternative names:
            "PO number"
            "Purchase order number"
            "Order Number (NO)"
            "Buyer order number"
            "Your order reference number"
            "PO No"
            "Customer PO"
            "Cust. PO No"
            "Manual No"
            "Order Ref"
        
        3.2 Once a "PO Number" is extracted, it should be validated based on the following criteria:
            3a) It must contain exactly 10 characters.
            3b) All characters of the "PO Number" should be digits.
            If the extracted "PO Number" does not meet criteria 3a or 3b, it should be flagged as "wrong PO number".
        
        3.3 Additionally, there are edge cases where the "PO Number" might have more than 10 characters, such as:
            * 2341234562(1748)
            * 2341234562_1748
            * 2341234562 1748   
            
            In these cases, "PO Number" is only upto the special character (i.e., "(", "_", or " "). 
            In this example, the final output should be ["2341234562"]. 
        
        Requirement:
            Identifies all "PO Numbers" based on the alternative names.
            Check for the edge cases.
            Validates each extracted "PO Number" based on the criteria mentioned above.
            Data type of the "Invoice Amount" is str.

    4. Suspended Tax Amount
        Need to extract the "Suspended Vat" amount. 
        Note that the "Suspended Vat" can also be referred to as "SVAT" or "Suspended Tax". 
        
        Follow these conditions:
            The "Suspended Vat" amount should be a numerical value, which can include decimal points.
            If the invoice does not have a "Suspended Vat" amount, the default value should be 0.
            
        Additional Instructions:
            Ensure to search for all possible synonyms ("SVAT", "Suspended Vat", "Suspended Tax").
            Accurately extract the numerical value associated with these terms.
            If none of these terms are found or if no numerical value is associated with them, set the "suspended_vat_amount" to 0.
            Data type of the "Invoice Amount" is str.

    5. Vat Amount
        Need to extract the "Vat" amount. Note that the "Vat" can also be referred to as "Tax". 
        
        Follow these conditions:
            The "Vat" amount should be a numerical value, which can include decimal points.
            If the invoice does not have a "Vat" amount, the default value should be 0.

        Additional Instructions:
            Ensure to search for all possible synonyms ("Vat", "Tax").
            Accurately extract the numerical value associated with these terms.
            If none of these terms are found or if no numerical value is associated with them, set the "vat_amount" to 0.
            Data type of the "Invoice Amount" is str.

    6. Invoice Amount
        Need to extract the "Invoice Amount" from the invoice. 
        The "Invoice Amount" can be referred to using different terms, including but not limited to:
            Invoice Amount
            Invoice Value
            Grand Total
            Total Amount
            Invoice Total
            Gross Value
        
        Please follow these steps:
        
            Identify the section of the invoice where the total amount is listed. Look for the following synonyms to locate this section:
                Invoice Amount
                Invoice Value
                Grand Total
                Total Amount
                Invoice Total
                Gross Value
        
            Extract the numerical value associated with the identified term. 
            
            The value should be a number and can include decimal points.

            Check the extracted numerical value for formatting issues such as improperly placed decimal points. 
                e.g., "2145.046.40" should be interpreted as "2145046.40"
                 Assume the rightmost part after the last decimal point is the actual decimal part.

            Data type of the "Invoice Amount" is str.

    7. Sub Total
        Need to extract the "Sub Total" from the invoice. 
        The "Sub Total" can be referred to using different terms, including but not limited to:
            Sub Total
            Sub Amount
            Net Total
            Net Amount
        
        Please follow these steps:
            Identify the section of the invoice where the sub total amount is listed. Look for the following synonyms to locate this section:
                Sub Total
                Sub Amount
                Net Total
                Net Amount
                
            Extract the numerical value associated with the identified term. 
            
            The value should be a number and can include decimal points.
            
            Ensure that the extracted value is the intermediate total amount before any taxes, discounts, or additional charges are applied, not the final total amount due on the invoice.

            Check the extracted numerical value for formatting issues such as improperly placed decimal points. 
                e.g., "2145.046.40" should be interpreted as "2145046.40". 
                 Assume the rightmost part after the last decimal point is the actual decimal part.
                        
            Output the extracted numerical value as the "Sub Total."

            Data type of the "Invoice Amount" is str.

    8. Delivery Note Number Validation
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
            
     9. Invoice Number
        'Invoice No' Consider alternative names such as:
            Invoice No
            Invoice number	
            Invoice Ref
            Invoice Reference
            Our reference No

General Rules
If any value is missing, set it to null only.
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
            (
                invoice_date, currency, po_number,
                suspended_tax_amount, vat_amount, delivery_note_number,
                invoice_amount, invoice_no, sub_total,
            ) = get_openai_response(base64_image,prompt)

            suspended_tax_amount = convert_string_to_amount(suspended_tax_amount)
            vat_amount = convert_string_to_amount(vat_amount)
            invoice_amount = convert_string_to_amount(invoice_amount)
            sub_total = convert_string_to_amount(sub_total)

            invoice_type = 'Invoice'
            if suspended_tax_amount > 0:
                invoice_type = 'SVAT Invoice'
            elif vat_amount > 0:
                invoice_type = 'Tax Invoice'

            validated_po_number = convert_po_num_to_list(po_number)

            if invoice_no or po_number  or invoice_date or invoice_amount or delivery_note_number:
                desired_output = {
                    "invoice_date": invoice_date,
                    "currency": currency,
                    "po_number": validated_po_number,
                    
                    "suspended_tax_amount": suspended_tax_amount,
                    "invoice_tax_amount": vat_amount,
                    "delivery_note_number": delivery_note_number,
                    
                    "invoice_amount": invoice_amount,            
                    "invoice_no": invoice_no,
                    "sub_total": sub_total,
                    
                    "invoice_type": invoice_type,
                    "filename": None,
                    "sbu": None,
                    "comment": None
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