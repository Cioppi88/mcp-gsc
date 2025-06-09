from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import os
import uvicorn
import json
import logging
import asyncio
from typing import Any, Dict, Optional, AsyncGenerator
import uuid

app = FastAPI(title="GSC MCP Server", version="1.0.0")

# Configurazione CORS - importante per n8n
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

# Definizione dei tool MCP
TOOLS_DEFINITION = [
    {
        "name": "list_properties",
        "description": "Lista tutte le proprietà Google Search Console disponibili per l'account",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_search_analytics",
        "description": "Ottieni dati di analisi di ricerca (query, clicks, impressions, CTR) per un sito specifico",
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": "URL completo del sito (es: https://www.moleskine.com/)"
                },
                "start_date": {
                    "type": "string",
                    "description": "Data di inizio in formato YYYY-MM-DD (default: 30 giorni fa)"
                },
                "end_date": {
                    "type": "string",
                    "description": "Data di fine in formato YYYY-MM-DD (default: oggi)"
                }
            },
            "required": ["site_url"]
        }
    },
    {
        "name": "get_site_details",
        "description": "Ottieni dettagli di verifica e configurazione per un sito specifico",
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": "URL completo del sito (es: https://www.instilla.it/)"
                }
            },
            "required": ["site_url"]
        }
    }
]

def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Esegue un tool specifico"""
    try:
        if not gsc_service:
            raise Exception(f"GSC service non disponibile: {gsc_error}")

        if tool_name == "list_properties":
            sites = gsc_service.sites().list().execute()
            properties = [site['siteUrl'] for site in sites.get('siteEntry', [])]
            return {
                "success": True,
                "properties": properties,
                "count": len(properties)
            }

        elif tool_name == "get_search_analytics":
            site_url = arguments.get('site_url')
            start_date = arguments.get('start_date', '2024-05-01')
            end_date = arguments.get('end_date', '2024-06-09')

            if not site_url:
                raise ValueError("site_url è richiesto")

            search_request = {
                'startDate': start_date,
                'endDate': end_date,
                'dimensions': ['query'],
                'rowLimit': 25
            }

            response = gsc_service.searchanalytics().query(
                siteUrl=site_url, body=search_request
            ).execute()

            analytics_data = response.get('rows', [])
            
            return {
                "success": True,
                "site_url": site_url,
                "period": f"{start_date} to {end_date}",
                "total_queries": len(analytics_data),
                "top_queries": analytics_data[:10],
                "summary": {
                    "total_clicks": sum(row.get('clicks', 0) for row in analytics_data),
                    "total_impressions": sum(row.get('impressions', 0) for row in analytics_data)
                }
            }

        elif tool_name == "get_site_details":
            site_url = arguments.get('site_url')
            if not site_url:
                raise ValueError("site_url è richiesto")

            site_info = gsc_service.sites().get(siteUrl=site_url).execute()
            return {
                "success": True,
                "site_url": site_url,
                "verification_method": site_info.get('verificationMethod'),
                "permission_level": site_info.get('permissionLevel'),
                "verified": site_info.get('verified', False)
            }

        else:
            raise ValueError(f"Tool sconosciuto: {tool_name}")

    except Exception as e:
        logger.error(f"Errore esecuzione tool {tool_name}: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "tool": tool_name
        }

@app.get("/")
async def root():
    """Informazioni sul server"""
    return {
        "name": "Google Search Console MCP Server",
        "version": "1.0.0",
        "status": "running",
        "gsc_connected": gsc_service is not None,
        "gsc_error": gsc_error,
        "endpoints": {
            "mcp_sse": "/sse",
            "health": "/health",
            "test": "/test-credentials"
        },
        "tools_available": len(TOOLS_DEFINITION)
    }

@app.get("/health")
async def health_check():
    """Health check"""
    return {
        "status": "healthy",
        "gsc_service": "connected" if gsc_service else "error",
        "timestamp": "2024-06-09T12:00:00Z"
    }

@app.get("/test-credentials")
async def test_credentials():
    """Test delle credenziali GSC"""
    try:
        if not gsc_service:
            return {
                "status": "error",
                "message": f"GSC service non inizializzato: {gsc_error}"
            }

        sites = gsc_service.sites().list().execute()
        properties = [site['siteUrl'] for site in sites.get('siteEntry', [])]

        return {
            "status": "success",
            "message": "Credenziali GSC funzionanti",
            "properties_count": len(properties),
            "properties": properties
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Errore test credenziali: {str(e)}"
        }

@app.get("/sse")
async def mcp_sse_endpoint(request: Request):
    """Endpoint SSE per protocollo MCP compatibile con n8n"""
    
    async def generate_sse_stream():
        # Header SSE
        yield "event: connect\n"
        yield f"data: {json.dumps({'type': 'connection', 'status': 'connected'})}\n\n"
        
        # Invio informazioni server
        server_info = {
            "jsonrpc": "2.0",
            "method": "server/info",
            "params": {
                "name": "gsc-mcp-server",
                "version": "1.0.0",
                "capabilities": {
                    "tools": True
                }
            }
        }
        yield f"data: {json.dumps(server_info)}\n\n"
        
        # Invio lista tool
        tools_message = {
            "jsonrpc": "2.0", 
            "method": "tools/list",
            "params": {
                "tools": TOOLS_DEFINITION
            }
        }
        yield f"data: {json.dumps(tools_message)}\n\n"
        
        # Mantieni la connessione attiva
        try:
            while True:
                if await request.is_disconnected():
                    break
                    
                # Heartbeat ogni 30 secondi
                heartbeat = {
                    "type": "heartbeat",
                    "timestamp": "2024-06-09T12:00:00Z"
                }
                yield f"data: {json.dumps(heartbeat)}\n\n"
                await asyncio.sleep(30)
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Errore SSE stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate_sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "*"
        }
    )

@app.post("/sse")
async def handle_mcp_message(message: Dict[str, Any]):
    """Gestisce messaggi MCP via POST"""
    try:
        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id", "1")
        
        logger.info(f"Ricevuto messaggio MCP: {method}")
        
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "gsc-mcp-server",
                        "version": "1.0.0"
                    }
                }
            }
            
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": TOOLS_DEFINITION
                }
            }
            
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            result = execute_tool(tool_name, arguments)
            
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, ensure_ascii=False)
                        }
                    ]
                }
            }
            
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Metodo non trovato: {method}"
                }
            }
            
    except Exception as e:
        logger.error(f"Errore gestione messaggio MCP: {e}")
        return {
            "jsonrpc": "2.0",
            "id": message.get("id", "1"),
            "error": {
                "code": -32000,
                "message": str(e)
            }
        }

# Endpoint legacy per compatibilità
@app.post("/mcp")
async def legacy_mcp_endpoint(request: Dict[str, Any]):
    """Endpoint MCP legacy per compatibilità"""
    try:
        method = request.get("method")
        params = request.get("params", {})
        
        if method == "list_properties":
            result = execute_tool("list_properties", {})
        elif method == "get_search_analytics":
            result = execute_tool("get_search_analytics", params)
        elif method == "get_site_details":
            result = execute_tool("get_site_details", params)
        else:
            raise ValueError(f"Metodo non supportato: {method}")
            
        return {"result": result}
        
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"🚀 Starting GSC MCP Server on port {port}")
    logger.info(f"📊 GSC Service Status: {'✅ Connected' if gsc_service else '❌ Error'}")
    uvicorn.run(app, host="0.0.0.0", port=port)
