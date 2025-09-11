from string import Template
import json
from typing import Any, Dict, List
import msal
import requests
import base64
from app.settings import settings

PATH = "./app/utils/emails/"
IMG_PATH = f"{PATH}img/"
info = open(f"{PATH}config.json")
info = json.load(info)

USERNAME = settings.USERNAME
CLIENT_ID = settings.CLIENT_ID
CLIENT_SECRET = settings.CLIENT_SECRET
TENANT_ID = settings.TENANT_ID
AUTHORITY = f"https://login.microsoftonline.com/{settings.TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/.default"]
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
FRONTEND_URL = settings.FRONTEND_URL

TEMPLATES = {
    "restore_password": f"{PATH}template/body_restore_password.html"
}

IMAGE_PATHS = {
    "logo": [f"{IMG_PATH}logo.png", "png"],
    "firma": [f"{IMG_PATH}firma.jpg", "jpeg"],
}


def get_access_token():
    app = msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET)
    token_response = app.acquire_token_for_client(SCOPES)
    if "access_token" in token_response:
        return token_response["access_token"]
    else:
        return None


def load_email_template(template_path: str, name: str, token: str, reset_link: str, image_cids: Dict[str, List]) -> str:
    with open(template_path, "r", encoding="utf-8") as file:
        template = Template(file.read())

    return template.safe_substitute(name=name, token=token, reset_link=reset_link, **image_cids)


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def add_attachment(image_name: str, image_data: List[str], image_cid: str) -> Dict[str, Any]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": image_name,
        "contentType": f"image/{image_data[1]}",
        "contentBytes": encode_image(image_data[0]),
        "isInline": True,
        "contentId": image_cid
    }


def send_email(
    to_emails: List[str], subject: str, body: str, attachments
) -> bool:

    to_recipients = [
        {"emailAddress": {"address": email}} for email in to_emails
    ]

    access_token = get_access_token()
    if not access_token:
        return False

    email_data = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body},
            "toRecipients": to_recipients,
            "attachments": attachments
        }
    }

    headers = {"Authorization": f"Bearer {access_token}",
               "Content-Type": "application/json"}
    response = requests.post(
        f"{GRAPH_ENDPOINT}/users/{USERNAME}/sendMail", json=email_data, headers=headers
    )

    if response.status_code == 202:
        return True
    else:
        return False


def send_email_restore_password(to_email: str, name: str, token: str) -> bool:

    image_paths: Dict[str, List] = {
        "logo": IMAGE_PATHS["logo"]
    }

    image_cids: Dict[str, str] = {
        f"{key}_cid": f"image_{index}" for index, key in enumerate(
            image_paths.keys())
    }

    reset_link: str = f"{FRONTEND_URL}resetPassword/{token}"
    html_body: str = load_email_template(
        TEMPLATES["restore_password"], name, token, reset_link, image_cids
    )

    attachments: Dict[str, Any] = [
        add_attachment(image_name, image_data, image_cid)
        for image_name, image_data, image_cid in
        zip(image_paths.keys(), image_paths.values(), image_cids.values())
    ]

    return send_email(
        [to_email],
        "Recuperación de Contraseña",
        html_body,
        attachments
    )
