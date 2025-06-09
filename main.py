from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import os
import uvicorn
import json
import logging
import asyncio
from typing import Any, Dict, Optional, AsyncGenerator
import uuid
from datetime import datetime

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

# Inizializza GSC service
gsc_service = None
gsc_error = None

try:
    from env_helper import get_search_console_service
    gsc_service = get_search_console_service()
    logger.info("✅ Google Search Console service inizializzato")
except Exception as e:
    gsc_error = str(e)
    logger.error(f"❌ Errore GSC service: {e}")

# Store per connessioni SSE attive
active_connections = {}

class MCPServerSSE:
    def __init__(self):
        self.tools = [
            {
                "name": "list_properties",
                "description": "Lista tutte le proprietà Google Search Console disponibili",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_search_analytics", 
                "description": "Ottieni dati di analisi di ricerca per un sito specifico",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "site_url": {
                            "type": "string",
                            "description": "URL del sito (es: https://www.example.com/)"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Data di inizio in formato YYYY-MM-DD"
                        },
                        "end_date": {
                            "type": "string", 
                            "description": "Data di fine in formato YYYY-MM-DD"
                        }
                    },
                    "required": ["site_url"]
                }
            },
            {
                "name": "get_site_details",
                "description": "Ottieni dettagli specifici per un sito in Google Search Console",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "site_url": {
                            "type": "string",
                            "description": "URL del sito (es: https://www.example.com/)"
                        }
                    },
                    "required": ["site_url"]
                }
            }
        ]

    def create_mcp_message(self, msg_type: str, id: str, result: Any = None, error: Any = None):
        """Crea un messaggio MCP standard"""
        message = {
            "jsonrpc": "2.0",
            "id": id
        }
        
        if error:
            message["error"] = error
        else:
            message["result"] = result
            
        return message

    async def handle_initialize(self, params: Dict) -> Dict:
        """Gestisce l'inizializzazione MCP"""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "listChanged": False
                },
                "logging": {},
                "experimental": {}
            },
            "serverInfo": {
                "name": "gsc-mcp-server",
                "version": "1.0.0"
            }
        }

    async def handle_tools_list(self, params: Dict) -> Dict:
        """Lista i tool disponibili"""
        return {"tools": self.tools}

    async def handle_tools_call(self, params: Dict) -> Dict:
        """Esegue un tool"""
        try:
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if not gsc_service:
                raise Exception(f"GSC service non disponibile: {gsc_error}")
            
            if tool_name == "list_properties":
                sites = gsc_service.sites().list().execute()
                result = {"properties": [site['siteUrl'] for site in sites.get('siteEntry', [])]}
                
            elif tool_name == "get_search_analytics":
                site_url = arguments.get('site_url')
                start_date = arguments.get('start_date', '2024-01-01')
                end_date = arguments.get('end_date', '2024-12-31')
                
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
                
            elif tool_name == "get_site_details":
                site_url = arguments.get('site_url')
                if not site_url:
                    raise ValueError("site_url richiesto")
                    
                site_info = gsc_service.sites().get(siteUrl=site_url).execute()
                result = {"site_details": site_info}
                
            else:
                raise ValueError(f"Tool sconosciuto: {tool_name}")
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2, ensure_ascii=False)
                    }
                ]
            }
            
        except Exception as e:
            raise Exception(f"Errore nell'esecuzione del tool: {str(e)}")

    async def process_message(self, message: Dict) -> Dict:
        """Processa un messaggio MCP"""
        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")
        
        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            else:
                raise Exception(f"Metodo non supportato: {method}")
                
            return self.create_mcp_message("result", msg_id, result)
            
        except Exception as e:
            error = {
                "code": -32000,
                "message": str(e)
            }
            return self.create_mcp_message("error", msg_id, error=error)

mcp_server = MCPServerSSE()

@app.get("/")
async def root():
    return {
        "message": "GSC MCP Server is running", 
        "status": "ok",
        "gsc_connected": gsc_service is not None,
        "gsc_error": gsc_error if gsc_service is None else None,
        "mcp_endpoints": {
            "sse": "/sse",
            "rest": "/mcp"
        }
    }

@app.get("/sse")
async def sse_endpoint(request: Request):
    """Endpoint SSE per connessioni MCP"""
    
    async def event_generator() -> AsyncGenerator[str, None]:
        connection_id = str(uuid.uuid4())
        active_connections[connection_id] = True
        
        try:
            # Invia messaggio di connessione
            yield f"data: {json.dumps({'type': 'connection', 'id': connection_id})}\n\n"
            
            while active_connections.get(connection_id, False):
                # Controlla se il client è ancora connesso
                if await request.is_disconnected():
                    break
                    
                # Heartbeat ogni 30 secondi
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()})}\n\n"
                await asyncio.sleep(30)
                
        except Exception as e:
            logger.error(f"Errore SSE: {e}")
        finally:
            active_connections.pop(connection_id, None)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.post("/sse")
async def sse_message_handler(message: Dict[str, Any]):
    """Gestisce messaggi MCP via POST (per n8n)"""
    try:
        response = await mcp_server.process_message(message)
        return response
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32000,
                "message": str(e)
            }
        }

# Mantieni i vecchi endpoint per compatibilità
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "gsc-mcp-server"}

@app.get("/test-credentials")
async def test_gsc_credentials():
    """Testa le credenziali Google Search Console"""
    try:
        if not gsc_service:
            return {
                "status": "error", 
                "message": "GSC service non inizializzato",
                "error_details": gsc_error
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

@app.post("/mcp")
async def handle_mcp_request(request: MCPRequest):
    """Endpoint MCP REST legacy"""
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
    return {"tools": mcp_server.tools}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
