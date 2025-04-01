from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Dict, Any, List, Optional
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
    """Get stock quote data for given symbols
    
    Args:
        symbols: List of stock codes, e.g. ["HK.00700", "US.AAPL", "SH.600519"]
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
    """
    ret, data = quote_ctx.get_stock_quote(symbols)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_market_snapshot(symbols: List[str]) -> Dict[str, Any]:
    """Get market snapshot for given symbols
    
    Args:
        symbols: List of stock codes, e.g. ["HK.00700", "US.AAPL", "SH.600519"]
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
    """
    ret, data = quote_ctx.get_market_snapshot(symbols)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_cur_kline(symbol: str, ktype: str, count: int = 100) -> Dict[str, Any]:
    """Get current K-line data
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL", "SH.600519"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
        ktype: K-line type, options:
            - "K_1M": 1 minute
            - "K_3M": 3 minutes
            - "K_5M": 5 minutes
            - "K_15M": 15 minutes
            - "K_30M": 30 minutes
            - "K_60M": 60 minutes
            - "K_DAY": Daily
            - "K_WEEK": Weekly
            - "K_MON": Monthly
        count: Number of K-lines to return (default: 100)
            Range: 1-1000
    """
    ret, data = quote_ctx.get_cur_kline(symbol, ktype, count)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_history_kline(symbol: str, ktype: str, start: str, end: str, count: int = 100) -> Dict[str, Any]:
    """Get historical K-line data
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL", "SH.600519"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
        ktype: K-line type, options:
            - "K_1M": 1 minute
            - "K_3M": 3 minutes
            - "K_5M": 5 minutes
            - "K_15M": 15 minutes
            - "K_30M": 30 minutes
            - "K_60M": 60 minutes
            - "K_DAY": Daily
            - "K_WEEK": Weekly
            - "K_MON": Monthly
        start: Start date in format "YYYY-MM-DD"
        end: End date in format "YYYY-MM-DD"
        count: Number of K-lines to return (default: 100)
            Range: 1-1000
    
    Note:
        - Limited to 30 stocks per 30 days
        - Used quota will be automatically released after 30 days
    """
    ret, data, page_req_key = quote_ctx.request_history_kline(
        code=symbol,
        start=start,
        end=end,
        ktype=ktype,
        max_count=count
    )
    
    if ret != RET_OK:
        return {'error': data}
    
    result = data.to_dict()
    
    # If there are more pages, continue fetching
    while page_req_key is not None:
        ret, data, page_req_key = quote_ctx.request_history_kline(
            code=symbol,
            start=start,
            end=end,
            ktype=ktype,
            max_count=count,
            page_req_key=page_req_key
        )
        if ret != RET_OK:
            return {'error': data}
        # Append new data to result
        new_data = data.to_dict()
        for key in result:
            if isinstance(result[key], list):
                result[key].extend(new_data[key])
    
    return result

@mcp.tool()
async def get_rt_data(symbol: str) -> Dict[str, Any]:
    """Get real-time data
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL", "SH.600519"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
    """
    ret, data = quote_ctx.get_rt_data(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_ticker(symbol: str) -> Dict[str, Any]:
    """Get ticker data
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL", "SH.600519"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
    """
    ret, data = quote_ctx.get_ticker(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_order_book(symbol: str) -> Dict[str, Any]:
    """Get order book data
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL", "SH.600519"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
    """
    ret, data = quote_ctx.get_order_book(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_broker_queue(symbol: str) -> Dict[str, Any]:
    """Get broker queue data
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL", "SH.600519"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
    """
    ret, data = quote_ctx.get_broker_queue(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

# Subscription Tools
@mcp.tool()
async def subscribe(symbols: List[str], sub_types: List[str]) -> Dict[str, Any]:
    """Subscribe to real-time data
    
    Args:
        symbols: List of stock codes, e.g. ["HK.00700", "US.AAPL"]
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
        sub_types: List of subscription types, options:
            - "QUOTE": Basic quote (price, volume, etc.)
            - "ORDER_BOOK": Order book (bid/ask)
            - "TICKER": Ticker (trades)
            - "RT_DATA": Real-time data
            - "BROKER": Broker queue
            - "K_1M": 1-minute K-line
            - "K_5M": 5-minute K-line
            - "K_15M": 15-minute K-line
            - "K_30M": 30-minute K-line
            - "K_60M": 60-minute K-line
            - "K_DAY": Daily K-line
            - "K_WEEK": Weekly K-line
            - "K_MON": Monthly K-line
    
    Note:
        - Maximum 100 symbols per request
        - Maximum 5 subscription types per request
    """
    for symbol in symbols:
        for sub_type in sub_types:
            ret, data = quote_ctx.subscribe(symbol, sub_type)
            if ret != RET_OK:
                return {'error': data}
    return {"status": "success"}

@mcp.tool()
async def unsubscribe(symbols: List[str], sub_types: List[str]) -> Dict[str, Any]:
    """Unsubscribe from real-time data
    
    Args:
        symbols: List of stock codes, e.g. ["HK.00700", "US.AAPL"]
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
            - SH: Shanghai stocks
            - SZ: Shenzhen stocks
        sub_types: List of subscription types, options:
            - "QUOTE": Basic quote (price, volume, etc.)
            - "ORDER_BOOK": Order book (bid/ask)
            - "TICKER": Ticker (trades)
            - "RT_DATA": Real-time data
            - "BROKER": Broker queue
            - "K_1M": 1-minute K-line
            - "K_5M": 5-minute K-line
            - "K_15M": 15-minute K-line
            - "K_30M": 30-minute K-line
            - "K_60M": 60-minute K-line
            - "K_DAY": Daily K-line
            - "K_WEEK": Weekly K-line
            - "K_MON": Monthly K-line
    """
    for symbol in symbols:
        for sub_type in sub_types:
            ret, data = quote_ctx.unsubscribe(symbol, sub_type)
            if ret != RET_OK:
                return {'error': data}
    return {"status": "success"}

# Derivatives Tools
@mcp.tool()
async def get_option_chain(symbol: str, start: str, end: str) -> Dict[str, Any]:
    """Get option chain data
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
        start: Start date in format "YYYY-MM-DD"
        end: End date in format "YYYY-MM-DD"
    """
    ret, data = quote_ctx.get_option_chain(symbol, start, end)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_option_expiration_date(symbol: str) -> Dict[str, Any]:
    """Get option expiration dates
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
    """
    ret, data = quote_ctx.get_option_expiration_date(symbol)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_option_condor(symbol: str, expiry: str, strike_price: float) -> Dict[str, Any]:
    """Get option condor strategy data
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
        expiry: Option expiration date in format "YYYY-MM-DD"
        strike_price: Strike price of the option
    """
    ret, data = quote_ctx.get_option_condor(symbol, expiry, strike_price)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_option_butterfly(symbol: str, expiry: str, strike_price: float) -> Dict[str, Any]:
    """Get option butterfly strategy data
    
    Args:
        symbol: Stock code, e.g. "HK.00700", "US.AAPL"
            Format: {market}.{code}
            - HK: Hong Kong stocks
            - US: US stocks
        expiry: Option expiration date in format "YYYY-MM-DD"
        strike_price: Strike price of the option
    """
    ret, data = quote_ctx.get_option_butterfly(symbol, expiry, strike_price)
    return data.to_dict() if ret == RET_OK else {'error': data}

# Account Query Tools
@mcp.tool()
async def get_account_list() -> Dict[str, Any]:
    """Get account list
    
    Returns:
        Dict containing account information including:
        - Account ID
        - Account type (CASH/MARGIN)
        - Account currency
        - Power (available funds)
    """
    ret, data = trade_ctx.get_account_list()
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_asset_info(trd_side: str) -> Dict[str, Any]:
    """Get asset information
    
    Args:
        trd_side: Trading market, options:
            - "HK": Hong Kong market
            - "US": US market
            - "CN": China A-shares market
    """
    ret, data = trade_ctx.get_asset_info(trd_side)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_asset_allocation(trd_side: str) -> Dict[str, Any]:
    """Get asset allocation information
    
    Args:
        trd_side: Trading market, options:
            - "HK": Hong Kong market
            - "US": US market
            - "CN": China A-shares market
    """
    ret, data = trade_ctx.get_asset_allocation(trd_side)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_position_list(trd_side: str = "HK") -> Dict[str, Any]:
    """Get position list for the account
    
    Args:
        trd_side: Trading market (default: "HK"), options:
            - "HK": Hong Kong market
            - "US": US market
            - "CN": China A-shares market
    """
    ret, data = trade_ctx.position_list_query(trd_side=trd_side)
    return data.to_dict() if ret == RET_OK else {'error': data}

# Market Information Tools
@mcp.tool()
async def get_market_state(market: str) -> Dict[str, Any]:
    """Get market state
    
    Args:
        market: Market code, options:
            - "HK": Hong Kong market (includes pre-market, continuous trading, afternoon, closing auction)
            - "US": US market (includes pre-market, continuous trading, after-hours)
            - "SH": Shanghai market (includes pre-opening, morning, afternoon, closing auction)
            - "SZ": Shenzhen market (includes pre-opening, morning, afternoon, closing auction)
    """
    ret, data = quote_ctx.get_market_state(market)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_security_info(market: str, code: str) -> Dict[str, Any]:
    """Get security information
    
    Args:
        market: Market code, options:
            - "HK": Hong Kong market
            - "US": US market
            - "SH": Shanghai market
            - "SZ": Shenzhen market
        code: Stock code without market prefix, e.g. "00700" for "HK.00700"
    
    Returns:
        Dict containing security information including:
        - Name
        - Lot size
        - Stock type
        - Total shares
        - Listing date
        - Industry
    """
    ret, data = quote_ctx.get_security_info(market, code)
    return data.to_dict() if ret == RET_OK else {'error': data}

@mcp.tool()
async def get_security_list(market: str) -> Dict[str, Any]:
    """Get security list
    
    Args:
        market: Market code, options:
            - "HK": Hong Kong market
            - "US": US market
            - "SH": Shanghai market
            - "SZ": Shenzhen market
    """
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

@mcp.tool()
async def get_stock_filter(base_filters: List[Dict[str, Any]] = None, 
                         accumulate_filters: List[Dict[str, Any]] = None,
                         financial_filters: List[Dict[str, Any]] = None,
                         market: str = None,
                         page: int = 1,
                         page_size: int = 200) -> Dict[str, Any]:
    """Get filtered stock list based on conditions
    
    Args:
        base_filters: List of base filters with structure:
            {
                "field_name": int,  # StockField enum value
                "filter_min": float,  # Optional minimum value
                "filter_max": float,  # Optional maximum value
                "is_no_filter": bool,  # Optional, whether to skip filtering
                "sort_dir": int  # Optional, sort direction (0: No sort, 1: Ascending, 2: Descending)
            }
        accumulate_filters: List of accumulate filters with structure:
            {
                "field_name": int,  # AccumulateField enum value
                "filter_min": float,
                "filter_max": float,
                "is_no_filter": bool,
                "sort_dir": int,  # 0: No sort, 1: Ascending, 2: Descending
                "days": int  # Required, number of days to accumulate
            }
        financial_filters: List of financial filters with structure:
            {
                "field_name": int,  # FinancialField enum value
                "filter_min": float,
                "filter_max": float,
                "is_no_filter": bool,
                "sort_dir": int,  # 0: No sort, 1: Ascending, 2: Descending
                "quarter": int  # Required, financial quarter
            }
        market: Market code, options:
            - "HK.Motherboard": Hong Kong Main Board
            - "HK.GEM": Hong Kong GEM
            - "HK.BK1911": H-Share Main Board
            - "HK.BK1912": H-Share GEM
            - "US.NYSE": NYSE
            - "US.AMEX": AMEX
            - "US.NASDAQ": NASDAQ
            - "SH.3000000": Shanghai Main Board
            - "SZ.3000001": Shenzhen Main Board
            - "SZ.3000004": Shenzhen ChiNext
        page: Page number, starting from 1 (default: 1)
        page_size: Number of results per page, max 200 (default: 200)
    """
    # Create filter request
    req = {
        "begin": (page - 1) * page_size,
        "num": page_size
    }
    
    # Add market filter if specified
    if market:
        req["plate"] = {"plate_code": market}
    
    # Add base filters
    if base_filters:
        req["baseFilterList"] = []
        for f in base_filters:
            filter_item = {"fieldName": f["field_name"]}
            if "filter_min" in f:
                filter_item["filterMin"] = f["filter_min"]
            if "filter_max" in f:
                filter_item["filterMax"] = f["filter_max"]
            if "is_no_filter" in f:
                filter_item["isNoFilter"] = f["is_no_filter"]
            if "sort_dir" in f:
                filter_item["sortDir"] = f["sort_dir"]
            req["baseFilterList"].append(filter_item)
    
    # Add accumulate filters
    if accumulate_filters:
        req["accumulateFilterList"] = []
        for f in accumulate_filters:
            filter_item = {
                "fieldName": f["field_name"],
                "days": f["days"]
            }
            if "filter_min" in f:
                filter_item["filterMin"] = f["filter_min"]
            if "filter_max" in f:
                filter_item["filterMax"] = f["filter_max"]
            if "is_no_filter" in f:
                filter_item["isNoFilter"] = f["is_no_filter"]
            if "sort_dir" in f:
                filter_item["sortDir"] = f["sort_dir"]
            req["accumulateFilterList"].append(filter_item)
    
    # Add financial filters
    if financial_filters:
        req["financialFilterList"] = []
        for f in financial_filters:
            filter_item = {
                "fieldName": f["field_name"],
                "quarter": f["quarter"]
            }
            if "filter_min" in f:
                filter_item["filterMin"] = f["filter_min"]
            if "filter_max" in f:
                filter_item["filterMax"] = f["filter_max"]
            if "is_no_filter" in f:
                filter_item["isNoFilter"] = f["is_no_filter"]
            if "sort_dir" in f:
                filter_item["sortDir"] = f["sort_dir"]
            req["financialFilterList"].append(filter_item)

    ret, data = quote_ctx.get_stock_filter(req)
    return data.to_dict() if ret == RET_OK else {'error': data}

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