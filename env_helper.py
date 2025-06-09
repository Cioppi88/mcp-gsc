import os
import json
import base64
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

def get_google_credentials():
    """
    Recupera le credenziali Google dalle variabili d'ambiente
    """
    try:
        # Recupera la chiave encodata da Railway
        encoded_key = os.getenv('GOOGLE_SERVICE_ACCOUNT_KEY')
        if not encoded_key:
            raise Exception("GOOGLE_SERVICE_ACCOUNT_KEY non trovata nelle variabili d'ambiente")
        
        # Decodifica da base64
        service_account_info = json.loads(
            base64.b64decode(encoded_key).decode('utf-8')
        )
        
        # Crea le credenziali
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=['https://www.googleapis.com/auth/webmasters']
        )
        
        return credentials
        
    except Exception as e:
        print(f"Errore nel caricamento delle credenziali: {e}")
        raise e

def get_search_console_service():
    """
    Crea il servizio Google Search Console
    """
    credentials = get_google_credentials()
    service = build('searchconsole', 'v1', credentials=credentials)
    return service

def test_credentials():
    """
    Testa se le credenziali funzionano
    """
    try:
        service = get_search_console_service()
        # Prova a listare le proprietà
        sites = service.sites().list().execute()
        print(f"✅ Credenziali OK! Trovate {len(sites.get('siteEntry', []))} proprietà")
        for site in sites.get('siteEntry', []):
            print(f"  - {site['siteUrl']}")
        return True
    except Exception as e:
        print(f"❌ Errore nel test delle credenziali: {e}")
        return False
