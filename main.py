from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import uvicorn
import json
import logging
from typing import Any, Dict, List, Optional

# Import del server GSC originale
from env_helper import get_search_console_service, test_credentials

app = FastAPI(title="GSC MCP Server", version="1.0.0")

# Configurazione CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In produzione, specifica domini specifici
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MCPRequest(BaseModel):
    method: str
    params: Optional[Dict[str, Any]] = None

class MCPResponse(BaseModel):
    result: Optional[Any] = None
    error: Optional[str] = None

# Inizializza il servizio Google Search Console
try:
    gsc_service = get_search_console_service()
    logger.info("Google Search Console service inizializzato con successo")
except Exception as e:
    logger.error(f"Errore nell'inizializzazione GSC service: {e}")
    gsc_service = None

@app.get("/")
async def root():
    return {"message": "GSC MCP Server is running", "status": "ok"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "gsc-mcp-server"}

@app.post("/mcp", response_model=MCPResponse)
async def handle_mcp_request(request: MCPRequest):
    """
    Gestisce le richieste MCP e le instrada al server GSC
    """
    try:
        if not gsc_service:
            raise Exception("Google Search Console service non disponibile")
            
        logger.info(f"Received MCP request: {request.method}")
        
        if request.method == "list_properties":
            # Lista tutte le proprietà GSC
            sites = gsc_service.sites().list().execute()
            result = {"properties": [site['siteUrl'] for site in sites.get('siteEntry', [])]}
            
        elif request.method == "get_search_analytics":
            # Analisi di ricerca per un sito specifico
            site_url = request.params.get('site_url')
            start_date = request.params.get('start_date', '2024-01-01')
            end_date = request.params.get('end_date', '2024-12-31')
            
            if not site_url:
                raise ValueError("site_url è richiesto per get_search_analytics")
            
            search_request = {
                'startDate': start_date,
                'endDate': end_date,
                'dimensions': ['query'],
                'rowLimit': 25
            }
            
            response = gsc_service.searchanalytics().query(
                siteUrl=site_url, 
                body=search_request
            ).execute()
            
            result = {
                "site_url": site_url,
                "analytics": response.get('rows', [])
            }
            
        elif request.method == "get_site_details":
            # Dettagli di un sito specifico
            site_url = request.params.get('site_url')
            if not site_url:
                raise ValueError("site_url è richiesto per get_site_details")
                
            site_info = gsc_service.sites().get(siteUrl=site_url).execute()
            result = {"site_details": site_info}
            
        else:
            raise HTTPException(status_code=400, detail=f"Metodo non implementato: {request.method}")
            
        return MCPResponse(result=result)
        
    except Exception as e:
        logger.error(f"Error handling MCP request: {str(e)}")
        return MCPResponse(error=str(e))

@app.get("/tools")
async def list_available_tools():
    """
    Restituisce la lista degli strumenti disponibili
    """
    tools = [
        "list_properties",
        "get_site_details", 
        "add_site",
        "delete_site",
        "get_search_analytics",
        "get_performance_overview",
        "check_indexing_issues",
        "inspect_url_enhanced",
        "get_sitemaps",
        "submit_sitemap"
    ]
    return {"available_tools": tools}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
