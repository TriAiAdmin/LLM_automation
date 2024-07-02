import shutil
import os
import base64
from pdf2image import convert_from_path
from PIL import Image
import io
import requests
import json
import pandas as pd
import argparse

with open('../../key.txt', 'r') as file:
    secret_key = file.read().strip()
os.environ['OPENAI_API_KEY'] = secret_key

def convert_pdf_to_images_all(pdf_path):
    return convert_from_path(pdf_path)

def encode_image_to_base64(image):
    if image.mode == 'RGBA':
        image = image.convert('RGB')
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def get_openai_response(base64_image,prompt):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"
    }
    
    payload = {
        "model": "gpt-4o",
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
        return (
                None, None, None, 
                None, None, None, 
                None, None, None, 
            )

def convert_string_to_amount(value):
    try:
        converted_value = value.replace('\s', '').replace(',', '')
        return float(converted_value)
    except:
        return 0

def get_sbu(mapping_dataset, value):
    _filtered_data = mapping_dataset[(mapping_dataset['min']<=value) & (mapping_dataset['max']>=value)]
    if len(_filtered_data)>=1:
        return list(_filtered_data['sbu'])[0]
    else:
        return None

def convert_po_number_to_int(value):
    return int(value)

def convert_po_num_to_list(po_num, sbu_mapping_table):
    validated_po_num = []
    cleaned_po_num = []
    sbu = None
    if (po_num == "null") or (po_num == "") or (po_num is None):
        po_num = []
    
    if type(po_num) is not list:
        po_num = [po_num]

    for i in po_num:
        _po_num = i.replace('O', '0').replace('o', '0')
        cleaned_po_num.append(_po_num)
        if len(_po_num)>=8:
            try:
                _po_num = convert_po_number_to_int(_po_num)
                _sbu = get_sbu(sbu_mapping_table, _po_num)
                if _sbu is not None:
                    validated_po_num.append(_po_num)
                    sbu = _sbu
                else:
                    validated_po_num.append('wrong po incorrect sbu')
            except Exception as e:
                validated_po_num.append('wrong po non_integer')
        else: 
            validated_po_num.append('wrong po')

    return validated_po_num, cleaned_po_num, sbu

def create_json_output(path_pdf, prompt, sbu_mapping_table):
    image_load_all = convert_pdf_to_images_all(path_pdf)
    final_cleaned_po_num = []
    final_validated_po_number = []
    final_invoice_date = ""
    final_currency = ""
    final_suspended_tax_amount = 0
    final_vat_amount = 0
    final_overall_tax = 0
    final_delivery_note_number = ""
    final_invoice_amount = 0
    final_invoice_no = ""
    final_sub_total = 0
    final_invoice_type = ""
    final_sbu = ""
    
    for image_load in image_load_all:
        base64_image = encode_image_to_base64(image_load)
        (
            invoice_date, currency, po_number,
            suspended_tax_amount, vat_amount, delivery_note_number,
            invoice_amount, invoice_no, sub_total,
        ) = get_openai_response(base64_image,prompt)

        suspended_tax_amount = convert_string_to_amount(suspended_tax_amount)
        vat_amount = convert_string_to_amount(vat_amount)
        invoice_amount = convert_string_to_amount(invoice_amount)
        sub_total = convert_string_to_amount(sub_total)
    
        overall_tax = 0
        
        invoice_type = 'Non-Tax Invoice'
        if suspended_tax_amount > 0:
            invoice_type = 'SVAT Invoice'
            overall_tax = suspended_tax_amount
        elif vat_amount > 0:
            invoice_type = 'Tax Invoice'
            overall_tax = vat_amount
    
        validated_po_number, cleaned_po_num, sbu = convert_po_num_to_list(po_number, sbu_mapping_table)
        final_cleaned_po_num += cleaned_po_num
        final_validated_po_number += validated_po_number

        final_invoice_date = invoice_date
        final_currency = currency
        final_suspended_tax_amount = suspended_tax_amount
        final_vat_amount = vat_amount
        final_overall_tax = overall_tax
        final_delivery_note_number = delivery_note_number
        final_invoice_amount = invoice_amount
        final_invoice_no = invoice_no
        final_sub_total = sub_total
        final_invoice_type = invoice_type
        final_sbu = sbu
    
    desired_output = {
        "invoice_date": final_invoice_date,
        "currency": final_currency,
        "po_number": final_cleaned_po_num,
        "validate_po_number": final_validated_po_number,
        
        "suspended_tax_amount": final_suspended_tax_amount,
        "vat_amount": final_vat_amount,
        "tax_amount": final_overall_tax,
        "delivery_note_number": final_delivery_note_number,

        "invoice_amount": final_invoice_amount,            
        "invoice_no": final_invoice_no,
        "sub_total": final_sub_total,
        "invoice_type": final_invoice_type,
        
        "sbu": final_sbu
    }
    formatted_json = json.dumps(desired_output, indent=4)
    return desired_output

prompt = '''Extract the following details from the invoice:
        Invoice Date,
        Currency Type,output_dc = {}
for i in batch_files:
    try:
        outcome = create_json_output(os.path.join(base_folder, i), prompt, sbu_mapping)
        if outcome is not None:
            output_dc[i] = outcome
            print('processed', i)
        else:
            print('error : ', i)
        break
    except:
        print('error : ', i)

select_columns = [
    'invoice_no', 'invoice_date', 'invoice_type', 'sbu', 
    'po_number', 'validate_po_number','delivery_note_number', 'sub_total', 
    'tax_amount', 'invoice_amount'
]

df_abc = pd.DataFrame.from_dict(output_dc, orient='index').reset_index().rename(columns={'index': 'filename'})
df_abc[select_columns].to_excel(os.path.join(output_folder, "output {}.xlsx".format(invoice_folder_name)), index=False)
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
            3a) It must contain 8 to 10 characters.
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
                AD
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
            Bill No

General Rules
If any value is missing, set it to null only.
    '''

base_location = "../../"
sbu_mapping = (
    pd.read_csv(os.path.join(base_location,'conf', 'sbu_type.csv'))
)
sbu_mapping[['min', 'max']] = sbu_mapping[['min', 'max']].apply(pd.to_numeric)


parser = argparse.ArgumentParser(description='activity')
parser.add_argument('file_name', type=str, help='pdf file name')
args = parser.parse_args()


invoice_folder_name = args.file_name
base_folder = os.path.join(base_location, 'data', invoice_folder_name)
output_folder = os.path.join(base_location, 'data')

all_files = [f for f in os.listdir(base_folder) if os.path.isfile(os.path.join(base_folder, f))]
batch_files = [f for f in all_files if f.endswith(('.pdf', '.png', '.jpg', '.jpeg'))]

output_dc = {}
for i in batch_files:
    try:
        outcome = create_json_output(os.path.join(base_folder, i), prompt, sbu_mapping)
        if outcome is not None:
            output_dc[i] = outcome
            print('processed', i)
        else:
            print('error : ', i)
    except:
        print('error : ', i)

select_columns = [
    'invoice_no', 'invoice_date', 'invoice_type', 'sbu', 
    'po_number', 'validate_po_number','delivery_note_number', 'sub_total', 
    'tax_amount', 'invoice_amount', 'filename'
]

df_abc = pd.DataFrame.from_dict(output_dc, orient='index').reset_index().rename(columns={'index': 'filename'})
df_abc[select_columns].to_excel(os.path.join(output_folder, "output {}.xlsx".format(invoice_folder_name)), index=False)

