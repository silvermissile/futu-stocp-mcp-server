from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Dict, Any, List
from futu import *
import json
import asyncio
from loguru import logger
import os
from dotenv import load_dotenv
from modelcontextprotocol.server.fastmcp import FastMCP
from modelcontextprotocol.types import TextContent, PromptMessage

# Load environment variables
load_dotenv()

app = FastAPI(title="Futu Stock MCP Server")

# Global Futu connection
quote_ctx = None
trade_ctx = None

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Dict[str, set]] = {}  # client_id -> {symbol -> set(sub_types)}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.subscriptions[client_id] = {}

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.subscriptions:
            del self.subscriptions[client_id]

    async def send_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)

    def add_subscription(self, client_id: str, symbol: str, sub_type: str):
        if client_id not in self.subscriptions:
            self.subscriptions[client_id] = {}
        if symbol not in self.subscriptions[client_id]:
            self.subscriptions[client_id][symbol] = set()
        self.subscriptions[client_id][symbol].add(sub_type)

    def remove_subscription(self, client_id: str, symbol: str, sub_type: str):
        if client_id in self.subscriptions and symbol in self.subscriptions[client_id]:
            self.subscriptions[client_id][symbol].discard(sub_type)
            if not self.subscriptions[client_id][symbol]:
                del self.subscriptions[client_id][symbol]
            if not self.subscriptions[client_id]:
                del self.subscriptions[client_id]

    def get_subscriptions(self, client_id: str) -> Dict[str, set]:
        return self.subscriptions.get(client_id, {})

manager = ConnectionManager()

@asynccontextmanager
async def server_lifespan(server: Server) -> AsyncIterator[dict]:
    """Manage server startup and shutdown lifecycle."""
    global quote_ctx, trade_ctx
    try:
        # Initialize Futu connection
        quote_ctx = OpenQuoteContext(
            host=os.getenv('FUTU_HOST', '127.0.0.1'),
            port=int(os.getenv('FUTU_PORT', '11111'))
        )
        trade_ctx = OpenTradeContext(
            host=os.getenv('FUTU_HOST', '127.0.0.1'),
            port=int(os.getenv('FUTU_PORT', '11111'))
        )
        logger.info("Successfully connected to Futu")
        yield {"quote_ctx": quote_ctx, "trade_ctx": trade_ctx}
    except Exception as e:
        logger.error(f"Failed to initialize Futu connection: {str(e)}")
        raise
    finally:
        if quote_ctx:
            quote_ctx.close()
        if trade_ctx:
            trade_ctx.close()

# Create MCP server instance
mcp = FastMCP("Futu Stock MCP Server", lifespan=server_lifespan)

# Market Data Tools
@mcp.tool()
async def get_stock_quote(symbols: List[str]) -> Dict[str, Any]:
    """Get stock quote data for given symbols"""
    ret, data = quote_ctx.get_stock_quote(symbols)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_market_snapshot(symbols: List[str]) -> Dict[str, Any]:
    """Get market snapshot for given symbols"""
    ret, data = quote_ctx.get_market_snapshot(symbols)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_cur_kline(symbol: str, ktype: str, count: int = 100) -> Dict[str, Any]:
    """Get current K-line data"""
    ret, data = quote_ctx.get_cur_kline(symbol, ktype, count)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_history_kline(symbol: str, ktype: str, start: str, end: str, count: int = 100) -> Dict[str, Any]:
    """Get historical K-line data"""
    ret, data = quote_ctx.get_history_kline(symbol, ktype, start, end, count)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_rt_data(symbol: str) -> Dict[str, Any]:
    """Get real-time data"""
    ret, data = quote_ctx.get_rt_data(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_ticker(symbol: str) -> Dict[str, Any]:
    """Get ticker data"""
    ret, data = quote_ctx.get_ticker(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_order_book(symbol: str) -> Dict[str, Any]:
    """Get order book data"""
    ret, data = quote_ctx.get_order_book(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_broker_queue(symbol: str) -> Dict[str, Any]:
    """Get broker queue data"""
    ret, data = quote_ctx.get_broker_queue(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

# Subscription Tools
@mcp.tool()
async def subscribe(symbols: List[str], sub_types: List[str]) -> Dict[str, Any]:
    """Subscribe to real-time data"""
    for symbol in symbols:
        for sub_type in sub_types:
            ret, data = quote_ctx.subscribe(symbol, sub_type)
            if ret != RET_OK:
                return {'error': data}
    return {"status": "success"}

@mcp.tool()
async def unsubscribe(symbols: List[str], sub_types: List[str]) -> Dict[str, Any]:
    """Unsubscribe from real-time data"""
    for symbol in symbols:
        for sub_type in sub_types:
            ret, data = quote_ctx.unsubscribe(symbol, sub_type)
            if ret != RET_OK:
                return {'error': data}
    return {"status": "success"}

# Derivatives Tools
@mcp.tool()
async def get_option_chain(symbol: str, start: str, end: str) -> Dict[str, Any]:
    """Get option chain data"""
    ret, data = quote_ctx.get_option_chain(symbol, start, end)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_option_expiration_date(symbol: str) -> Dict[str, Any]:
    """Get option expiration dates"""
    ret, data = quote_ctx.get_option_expiration_date(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_option_condor(symbol: str, expiry: str, strike_price: float) -> Dict[str, Any]:
    """Get option condor strategy data"""
    ret, data = quote_ctx.get_option_condor(symbol, expiry, strike_price)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_option_butterfly(symbol: str, expiry: str, strike_price: float) -> Dict[str, Any]:
    """Get option butterfly strategy data"""
    ret, data = quote_ctx.get_option_butterfly(symbol, expiry, strike_price)
    return data.to_dict() if ret == RET_OK else {'error': data}

# Account Query Tools
@mcp.tool()
async def get_account_list() -> Dict[str, Any]:
    """Get account list"""
    ret, data = trade_ctx.get_account_list()
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_asset_info(trd_side: str) -> Dict[str, Any]:
    """Get asset information"""
    ret, data = trade_ctx.get_asset_info(trd_side)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_asset_allocation(trd_side: str) -> Dict[str, Any]:
    """Get asset allocation information"""
    ret, data = trade_ctx.get_asset_allocation(trd_side)
    return data.to_dict() if ret == RET_OK else {'error': data}

# Market Information Tools
@mcp.tool()
async def get_market_state(market: str) -> Dict[str, Any]:
    """Get market state"""
    ret, data = quote_ctx.get_market_state(market)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_security_info(market: str, code: str) -> Dict[str, Any]:
    """Get security information"""
    ret, data = quote_ctx.get_security_info(market, code)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_security_list(market: str) -> Dict[str, Any]:
    """Get security list"""
    ret, data = quote_ctx.get_security_list(market)
    return data.to_dict() if ret == RET_OK else {'error': data}

# Resources
@mcp.resource("market://{symbol}")
async def get_market_data(symbol: str) -> Dict[str, Any]:
    """Get market data as a resource"""
    ret, data = quote_ctx.get_market_snapshot([symbol])
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.resource("kline://{symbol}/{ktype}")
async def get_kline_data(symbol: str, ktype: str) -> Dict[str, Any]:
    """Get K-line data as a resource"""
    ret, data = quote_ctx.get_cur_kline(symbol, ktype)
    return data.to_dict() if ret == RET_OK else {'error': data}

# Prompts
@mcp.prompt()
async def market_analysis(symbol: str) -> str:
    """Create a market analysis prompt"""
    return f"Please analyze the market data for {symbol}"

@mcp.prompt()
async def option_strategy(symbol: str, expiry: str) -> str:
    """Create an option strategy analysis prompt"""
    return f"Please analyze option strategies for {symbol} expiring on {expiry}"

@app.on_event("startup")
async def startup_event():
    if not init_futu_connection():
        logger.error("Failed to initialize Futu connection")
        raise Exception("Futu connection failed")

@app.on_event("shutdown")
async def shutdown_event():
    if quote_ctx:
        quote_ctx.close()
    if trade_ctx:
        trade_ctx.close()

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            await handle_message(data, client_id)
    except WebSocketDisconnect:
        manager.disconnect(client_id)

def create_error_response(request_id: str, message: str, code: int = -32000) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
            "data": None
        }
    }

def create_success_response(request_id: str, result: Any) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result
    }

async def handle_message(message: str, client_id: str):
    try:
        data = json.loads(message)
        method = data.get('method')
        params = data.get('params', {})
        request_id = data.get('id')

        if not method or not request_id:
            await manager.send_message(json.dumps(create_error_response(
                request_id,
                "Invalid request: missing method or id"
            )), client_id)
            return

        # Subscription Methods
        if method == 'subscribe':
            symbols = params.get('symbols', [])
            sub_types = params.get('sub_types', [])
            
            for symbol in symbols:
                for sub_type in sub_types:
                    ret, data = quote_ctx.subscribe(symbol, sub_type)
                    if ret == RET_OK:
                        manager.add_subscription(client_id, symbol, sub_type)
            
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                {"status": "success"}
            )), client_id)

        elif method == 'unsubscribe':
            symbols = params.get('symbols', [])
            sub_types = params.get('sub_types', [])
            
            for symbol in symbols:
                for sub_type in sub_types:
                    ret, data = quote_ctx.unsubscribe(symbol, sub_type)
                    if ret == RET_OK:
                        manager.remove_subscription(client_id, symbol, sub_type)
            
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                {"status": "success"}
            )), client_id)

        elif method == 'get_subscription':
            subscriptions = manager.get_subscriptions(client_id)
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                subscriptions
            )), client_id)

        # Market Data Methods
        elif method == 'get_stock_quote':
            ret, data = quote_ctx.get_stock_quote(params.get('symbols', []))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_market_snapshot':
            ret, data = quote_ctx.get_market_snapshot(params.get('symbols', []))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_cur_kline':
            ret, data = quote_ctx.get_cur_kline(
                params.get('symbol'),
                params.get('ktype'),
                params.get('count')
            )
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_history_kline':
            ret, data = quote_ctx.get_history_kline(
                params.get('symbol'),
                params.get('ktype'),
                params.get('start'),
                params.get('end'),
                params.get('count')
            )
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_rt_data':
            ret, data = quote_ctx.get_rt_data(params.get('symbol'))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_ticker':
            ret, data = quote_ctx.get_ticker(params.get('symbol'))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_order_book':
            ret, data = quote_ctx.get_order_book(params.get('symbol'))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_broker_queue':
            ret, data = quote_ctx.get_broker_queue(params.get('symbol'))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        # Derivatives Methods
        elif method == 'get_option_chain':
            ret, data = quote_ctx.get_option_chain(
                params.get('symbol'),
                params.get('start'),
                params.get('end')
            )
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_option_expiration_date':
            ret, data = quote_ctx.get_option_expiration_date(params.get('symbol'))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_option_condor':
            ret, data = quote_ctx.get_option_condor(
                params.get('symbol'),
                params.get('expiry'),
                params.get('strike_price')
            )
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_option_butterfly':
            ret, data = quote_ctx.get_option_butterfly(
                params.get('symbol'),
                params.get('expiry'),
                params.get('strike_price')
            )
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        # Account Query Methods
        elif method == 'get_account_list':
            ret, data = trade_ctx.get_account_list()
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_asset_info':
            ret, data = trade_ctx.get_asset_info(params.get('trd_side'))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_asset_allocation':
            ret, data = trade_ctx.get_asset_allocation(params.get('trd_side'))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        # Market Information Methods
        elif method == 'get_market_state':
            ret, data = quote_ctx.get_market_state(params.get('market'))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_security_info':
            ret, data = quote_ctx.get_security_info(
                params.get('market'),
                params.get('code')
            )
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        elif method == 'get_security_list':
            ret, data = quote_ctx.get_security_list(params.get('market'))
            await manager.send_message(json.dumps(create_success_response(
                request_id,
                data.to_dict() if ret == RET_OK else {'error': data}
            )), client_id)

        else:
            await manager.send_message(json.dumps(create_error_response(
                request_id,
                f'Unknown method: {method}'
            )), client_id)

    except Exception as e:
        await manager.send_message(json.dumps(create_error_response(
            request_id,
            str(e)
        )), client_id)

def init_futu_connection():
    global quote_ctx, trade_ctx
    try:
        # Initialize Futu connection
        quote_ctx = OpenQuoteContext(
            host=os.getenv('FUTU_HOST', '127.0.0.1'),
            port=int(os.getenv('FUTU_PORT', '11111'))
        )
        trade_ctx = OpenTradeContext(
            host=os.getenv('FUTU_HOST', '127.0.0.1'),
            port=int(os.getenv('FUTU_PORT', '11111'))
        )
        
        logger.info("Successfully connected to Futu")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Futu connection: {str(e)}")
        return False

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv('HOST', '0.0.0.0'), port=int(os.getenv('PORT', '8000')))
    mcp.run() 