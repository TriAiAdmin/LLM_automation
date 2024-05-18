from langchain_openai import ChatOpenAI
from langchain.schema.messages import HumanMessage, AIMessage
import streamlit as st
import base64
from PIL import Image
from dotenv import load_dotenv
import os
import fitz  # PyMuPDF
import io
import json

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

chain = ChatOpenAI(model="gpt-4o", max_tokens=2048, api_key=OPENAI_API_KEY)

def encode_image(image, format="PNG"):
    with io.BytesIO() as buffer:
        image.save(buffer, format=format)
        base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return base64_image

def pdf_to_images(pdf_file):
    images = []
    pdf_document = fitz.open(stream=pdf_file.read(), filetype="pdf")
    for page_num in range(len(pdf_document)):
        page = pdf_document.load_page(page_num)
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    return images

def get_response(b64image):
    msg = chain.invoke(
        [
            AIMessage(
                content="You are an intelligent OCR bot that can extract all relevant information from invoices and return the data in JSON format."
            ),
            HumanMessage(
                content=[
                    {"type": "image_url",
                     "image_url": {
                         "url": "data:image/png;base64," + b64image,
                         "details": "auto"
                     }
                     }
                ]
            )
        ]
    )
    return msg.content

def main():
    st.title("Invoice OCR")
    upload_file = st.file_uploader("Upload an image or PDF", type=["jpg", "jpeg", "png", "pdf"])
    
    if upload_file is not None:
        file_type = upload_file.type
        if file_type == "application/pdf":
            images = pdf_to_images(upload_file)
            for img in images:
                st.image(img, caption='Page from your PDF', use_column_width=True)
            st.success("PDF uploaded and processed successfully")
            b64_image = encode_image(images[0])  # Using the first page as an example
        else:
            image = Image.open(upload_file)
            st.image(image, caption='Your invoice', use_column_width=True)
            st.success("Image uploaded successfully")
            b64_image = encode_image(image, format="PNG")
        
        btn = st.button("Extract Information")
        if btn:
            response = get_response(b64_image)
            try:
                json_response = json.loads(response)
                st.json(json_response)
            except json.JSONDecodeError:
                st.error("Failed to decode JSON response")
                st.write(response)

if __name__ == "__main__":
    main()
