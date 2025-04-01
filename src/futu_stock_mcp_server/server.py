from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Dict, Any, List
from futu import OpenQuoteContext, OpenHKTradeContext, RET_OK
import json
import asyncio
from loguru import logger
import os
import sys
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, PromptMessage
from mcp.server import Server

# Get the project root directory and add it to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# Load environment variables from project root
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

# Configure logging
logger.remove()  # Remove default handler

# Get the project root directory
log_dir = os.path.join(project_root, "logs")
os.makedirs(log_dir, exist_ok=True)

# Add file handler
logger.add(
    os.path.join(log_dir, "futu_server.log"),
    rotation="500 MB",
    retention="10 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
)

# Add console handler
logger.add(
    lambda msg: print(msg),
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
)

logger.info(f"Starting server with log directory: {log_dir}")

@asynccontextmanager
async def lifespan(server: Server):
    # Startup
    if not init_futu_connection():
        logger.error("Failed to initialize Futu connection")
        raise Exception("Futu connection failed")
    yield
    # Shutdown
    if quote_ctx:
        quote_ctx.close()
    if trade_ctx:
        trade_ctx.close()

# Global Futu connection
quote_ctx = None
trade_ctx = None

# Create MCP server instance
mcp = FastMCP("futu-stock-server", lifespan=lifespan)

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

@mcp.tool()
async def get_position_list(trd_side: str = "HK") -> Dict[str, Any]:
    """Get position list for the account"""
    ret, data = trade_ctx.position_list_query(trd_side=trd_side)
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

# Prompts
@mcp.prompt()
async def market_analysis(symbol: str) -> str:
    """Create a market analysis prompt"""
    return f"Please analyze the market data for {symbol}"

@mcp.prompt()
async def option_strategy(symbol: str, expiry: str) -> str:
    """Create an option strategy analysis prompt"""
    return f"Please analyze option strategies for {symbol} expiring on {expiry}"

def init_futu_connection():
    global quote_ctx, trade_ctx
    try:
        # Initialize Futu connection
        quote_ctx = OpenQuoteContext(
            host=os.getenv('FUTU_HOST', '127.0.0.1'),
            port=int(os.getenv('FUTU_PORT', '11111'))
        )
        trade_ctx = OpenHKTradeContext(
            host=os.getenv('FUTU_HOST', '127.0.0.1'),
            port=int(os.getenv('FUTU_PORT', '11111'))
        )
        
        logger.info("Successfully connected to Futu")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Futu connection: {str(e)}")
        return False

if __name__ == "__main__":
    try:
        logger.info("Initializing Futu connection...")
        if init_futu_connection():
            logger.info("Successfully initialized Futu connection")
            logger.info("Starting MCP server in stdio mode...")
            mcp.run(transport='stdio')
        else:
            logger.error("Failed to initialize Futu connection. Server will not start.")
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}")
        raise 