import os
import json
import base64
from google.oauth2 import service_account
from googleapiclient.discovery import build

def get_google_credentials():
    """Recupera credenziali Google dalle variabili d'ambiente"""
    try:
        encoded_key = os.getenv('GOOGLE_SERVICE_ACCOUNT_KEY')
        if not encoded_key:
            raise Exception("GOOGLE_SERVICE_ACCOUNT_KEY mancante")
        
        # Decodifica da base64
        service_account_info = json.loads(
            base64.b64decode(encoded_key).decode('utf-8')
        )
        
        # Crea credenziali
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=['https://www.googleapis.com/auth/webmasters']
        )
        
        return credentials
        
    except Exception as e:
        print(f"Errore credenziali: {e}")
        raise e

def get_search_console_service():
    """Crea servizio Google Search Console"""
    credentials = get_google_credentials()
    service = build('searchconsole', 'v1', credentials=credentials)
    return service
