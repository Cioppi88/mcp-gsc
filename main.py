from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import uvicorn
import json
import logging
from typing import Any, Dict, Optional

app = FastAPI(title="GSC MCP Server", version="1.0.0")

# Configurazione CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# Prova a inizializzare GSC service
gsc_service = None
gsc_error = None

try:
    from env_helper import get_search_console_service
    gsc_service = get_search_console_service()
    logger.info("✅ Google Search Console service inizializzato")
except Exception as e:
    gsc_error = str(e)
    logger.error(f"❌ Errore GSC service: {e}")

@app.get("/")
async def root():
    return {
        "message": "GSC MCP Server is running", 
        "status": "ok",
        "gsc_connected": gsc_service is not None,
        "gsc_error": gsc_error if gsc_service is None else None,
        "environment_check": {
            "has_google_key": "GOOGLE_SERVICE_ACCOUNT_KEY" in os.environ,
            "google_key_length": len(os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "")),
            "port": os.environ.get("PORT", "not_set")
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "gsc-mcp-server"}

@app.get("/debug")
async def debug_info():
    """Endpoint per debug - mostra info ambiente"""
    return {
        "environment_variables": {
            "has_google_key": "GOOGLE_SERVICE_ACCOUNT_KEY" in os.environ,
            "google_key_length": len(os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "")) if "GOOGLE_SERVICE_ACCOUNT_KEY" in os.environ else 0,
            "port": os.environ.get("PORT"),
            "project_id": os.environ.get("GOOGLE_PROJECT_ID"),
            "all_env_keys": list(os.environ.keys())
        },
        "gsc_service_status": {
            "initialized": gsc_service is not None,
            "error": gsc_error
        }
    }

@app.get("/test-credentials")
async def test_gsc_credentials():
    """Testa le credenziali Google Search Console"""
    try:
        if not gsc_service:
            return {
                "status": "error", 
                "message": "GSC service non inizializzato",
                "error_details": gsc_error,
                "has_env_var": "GOOGLE_SERVICE_ACCOUNT_KEY" in os.environ
            }
        
        sites = gsc_service.sites().list().execute()
        properties = [site['siteUrl'] for site in sites.get('siteEntry', [])]
        
        return {
            "status": "success",
            "message": "Credenziali OK",
            "properties_count": len(properties),
            "properties": properties
        }
        
    except Exception as e:
        return {"status": "error", "message": f"Errore: {str(e)}"}

@app.post("/mcp", response_model=MCPResponse)
async def handle_mcp_request(request: MCPRequest):
    """Gestisce le richieste MCP"""
    try:
        if not gsc_service:
            raise Exception(f"GSC service non disponibile: {gsc_error}")
            
        logger.info(f"MCP request: {request.method}")
        
        if request.method == "list_properties":
            sites = gsc_service.sites().list().execute()
            result = {"properties": [site['siteUrl'] for site in sites.get('siteEntry', [])]}
            
        elif request.method == "get_search_analytics":
            site_url = request.params.get('site_url')
            start_date = request.params.get('start_date', '2024-01-01')
            end_date = request.params.get('end_date', '2024-12-31')
            
            if not site_url:
                raise ValueError("site_url richiesto")
            
            search_request = {
                'startDate': start_date,
                'endDate': end_date,
                'dimensions': ['query'],
                'rowLimit': 25
            }
            
            response = gsc_service.searchanalytics().query(
                siteUrl=site_url, body=search_request
            ).execute()
            
            result = {
                "site_url": site_url,
                "period": f"{start_date} to {end_date}",
                "analytics": response.get('rows', [])
            }
            
        elif request.method == "get_site_details":
            site_url = request.params.get('site_url')
            if not site_url:
                raise ValueError("site_url richiesto")
                
            site_info = gsc_service.sites().get(siteUrl=site_url).execute()
            result = {"site_details": site_info}
            
        else:
            raise HTTPException(status_code=400, detail=f"Metodo sconosciuto: {request.method}")
            
        return MCPResponse(result=result)
        
    except Exception as e:
        logger.error(f"Errore MCP: {str(e)}")
        return MCPResponse(error=str(e))

@app.get("/tools")
async def list_available_tools():
    """Lista strumenti disponibili"""
    tools = [
        "list_properties",
        "get_site_details", 
        "get_search_analytics"
    ]
    return {"available_tools": tools}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
