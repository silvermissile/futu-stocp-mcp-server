from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Dict, Any, List, Optional
from futu import OpenQuoteContext, OpenSecTradeContext, TrdMarket, SecurityFirm, RET_OK
import json
import asyncio
from loguru import logger
import os
import sys
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, PromptMessage
from mcp.server import Server
import atexit
import signal
import fcntl
import psutil
import time

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

# PID file path
PID_FILE = os.path.join(project_root, '.futu_mcp.pid')
LOCK_FILE = os.path.join(project_root, '.futu_mcp.lock')

# Global variables
quote_ctx = None
trade_ctx = None
lock_fd = None
_is_shutting_down = False
_is_trade_initialized = False

def is_process_running(pid):
    """Check if a process with given PID is running"""
    try:
        return psutil.pid_exists(pid)
    except:
        return False

def cleanup_stale_processes():
    """Clean up any stale Futu processes"""
    global _is_shutting_down
    if _is_shutting_down:
        return
        
    try:
        # 只检查 PID 文件中的进程
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, 'r') as f:
                    old_pid = int(f.read().strip())
                    if old_pid != os.getpid():
                        try:
                            old_proc = psutil.Process(old_pid)
                            if any('futu_stock_mcp_server' in cmd for cmd in old_proc.cmdline()):
                                logger.info(f"Found stale process {old_pid}")
                                old_proc.terminate()
                                try:
                                    old_proc.wait(timeout=3)
                                except psutil.TimeoutExpired:
                                    old_proc.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
            except (IOError, ValueError):
                pass
            
            # 清理 PID 文件
            try:
                os.unlink(PID_FILE)
            except OSError:
                pass
                
        # 清理锁文件
        if os.path.exists(LOCK_FILE):
            try:
                os.unlink(LOCK_FILE)
            except OSError:
                pass
                
    except Exception as e:
        logger.error(f"Error cleaning up stale processes: {str(e)}")

def cleanup_connections():
    """Clean up Futu connections"""
    global quote_ctx, trade_ctx
    try:
        if quote_ctx:
            try:
                quote_ctx.close()
                logger.info("Successfully closed quote context")
            except Exception as e:
                logger.error(f"Error closing quote context: {str(e)}")
            quote_ctx = None
        
        if trade_ctx:
            try:
                trade_ctx.close()
                logger.info("Successfully closed trade context")
            except Exception as e:
                logger.error(f"Error closing trade context: {str(e)}")
            trade_ctx = None
            
        # 等待连接完全关闭
        time.sleep(1)
    except Exception as e:
        logger.error(f"Error during connection cleanup: {str(e)}")

def release_lock():
    """Release the process lock"""
    global lock_fd
    try:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            lock_fd = None
        if os.path.exists(LOCK_FILE):
            os.unlink(LOCK_FILE)
        if os.path.exists(PID_FILE):
            os.unlink(PID_FILE)
    except Exception as e:
        logger.error(f"Error releasing lock: {str(e)}")

def cleanup_all():
    """Clean up all resources on exit"""
    global _is_shutting_down
    if _is_shutting_down:
        return
    _is_shutting_down = True
    
    cleanup_connections()
    release_lock()
    cleanup_stale_processes()

def signal_handler(signum, frame):
    """Handle process signals"""
    global _is_shutting_down
    if _is_shutting_down:
        return
        
    # 只处理 SIGINT 和 SIGTERM
    if signum not in (signal.SIGINT, signal.SIGTERM):
        return
        
    logger.info(f"Received signal {signum}, cleaning up...")
    cleanup_all()
    sys.exit(0)

# Register cleanup functions
atexit.register(cleanup_all)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def acquire_lock():
    """Try to acquire the process lock"""
    try:
        # 先检查 PID 文件
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, 'r') as f:
                    old_pid = int(f.read().strip())
                    if old_pid != os.getpid() and psutil.pid_exists(old_pid):
                        try:
                            old_proc = psutil.Process(old_pid)
                            if any('futu_stock_mcp_server' in cmd for cmd in old_proc.cmdline()):
                                logger.error(f"Another instance is already running (PID: {old_pid})")
                                return None
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
            except (IOError, ValueError):
                pass
        
        # 创建锁文件
        lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            os.close(lock_fd)
            return None
            
        # 写入 PID 文件
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
            
        return lock_fd
    except Exception as e:
        logger.error(f"Failed to acquire lock: {str(e)}")
        if 'lock_fd' in locals():
            try:
                os.close(lock_fd)
            except:
                pass
        return None

def init_quote_connection():
    """Initialize quote connection only"""
    global quote_ctx
    
    try:
        # Check if OpenD is running by attempting to get global state
        try:
            temp_ctx = OpenQuoteContext(
                host=os.getenv('FUTU_HOST', '127.0.0.1'),
                port=int(os.getenv('FUTU_PORT', '11111'))
            )
            ret, _ = temp_ctx.get_global_state()
            temp_ctx.close()
            if ret != RET_OK:
                logger.error("OpenD is not running or not accessible")
                return False
        except Exception as e:
            logger.error(f"Failed to connect to OpenD: {str(e)}")
            return False

        # Initialize Futu connection
        quote_ctx = OpenQuoteContext(
            host=os.getenv('FUTU_HOST', '127.0.0.1'),
            port=int(os.getenv('FUTU_PORT', '11111'))
        )
        logger.info("Successfully connected to Futu Quote API")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize quote connection: {str(e)}")
        cleanup_connections()
        return False

def init_trade_connection():
    """Initialize trade connection only"""
    global trade_ctx, _is_trade_initialized
    
    if _is_trade_initialized and trade_ctx:
        return True
        
    try:
        # Initialize trade context with proper market access
        trade_env = os.getenv('FUTU_TRADE_ENV', 'SIMULATE')
        security_firm = getattr(SecurityFirm, os.getenv('FUTU_SECURITY_FIRM', 'FUTUSECURITIES'))
        
        # 只支持港股和美股
        market_map = {
            'HK': 1,  # TrdMarket.HK
            'US': 2   # TrdMarket.US
        }
        trd_market = market_map.get(os.getenv('FUTU_TRD_MARKET', 'HK'), 1)
        
        # 创建交易上下文
        trade_ctx = OpenSecTradeContext(
            filter_trdmarket=trd_market,
            host=os.getenv('FUTU_HOST', '127.0.0.1'),
            port=int(os.getenv('FUTU_PORT', '11111')),
            security_firm=security_firm
        )
            
        # 等待连接就绪
        time.sleep(1)
            
        # 验证连接状态
        if not trade_ctx:
            raise Exception("Failed to create trade context")
            
        # Set trade environment
        if hasattr(trade_ctx, 'set_trade_env'):
            ret, data = trade_ctx.set_trade_env(trade_env)
            if ret != RET_OK:
                logger.warning(f"Failed to set trade environment: {data}")
                
        # Verify account access and permissions
        ret, data = trade_ctx.get_acc_list()
        if ret != RET_OK:
            logger.warning(f"Failed to get account list: {data}")
            cleanup_connections()
            return False
            
        if data is None or len(data) == 0:
            logger.warning("No trading accounts available")
            cleanup_connections()
            return False
            
        # Convert DataFrame to records if necessary
        if hasattr(data, 'to_dict'):
            accounts = data.to_dict('records')
        else:
            accounts = data
            
        logger.info(f"Found {len(accounts)} trading account(s)")
        
        # 检查账户状态
        for acc in accounts:
            if isinstance(acc, dict):
                acc_id = acc.get('acc_id', 'Unknown')
                acc_type = acc.get('acc_type', 'Unknown')
                acc_state = acc.get('acc_state', 'Unknown')
                trd_env = acc.get('trd_env', 'Unknown')
                trd_market = acc.get('trd_market', 'Unknown')
            else:
                acc_id = getattr(acc, 'acc_id', 'Unknown')
                acc_type = getattr(acc, 'acc_type', 'Unknown')
                acc_state = getattr(acc, 'acc_state', 'Unknown')
                trd_env = getattr(acc, 'trd_env', 'Unknown')
                trd_market = getattr(acc, 'trd_market', 'Unknown')
                
            logger.info(f"Account: {acc_id}, Type: {acc_type}, State: {acc_state}, Environment: {trd_env}, Market: {trd_market}")
        
        _is_trade_initialized = True
        logger.info(f"Successfully initialized trade connection (Trade Environment: {trade_env}, Security Firm: {security_firm}, Market: {trd_market})")
        return True
            
    except Exception as e:
        logger.error(f"Failed to initialize trade connection: {str(e)}")
        cleanup_connections()
        _is_trade_initialized = False
        return False

def init_futu_connection():
    """Initialize both quote and trade connections"""
    return init_quote_connection()

@asynccontextmanager
async def lifespan(server: Server):
    # Startup - only initialize quote connection
    if not init_quote_connection():
        logger.error("Failed to initialize quote connection")
        raise Exception("Quote connection failed")
    try:
        yield
    finally:
        # Shutdown - ensure connections are closed
        cleanup_all()

# Create MCP server instance
mcp = FastMCP("futu-stock-server", lifespan=lifespan)

def handle_return_data(ret: int, data: Any) -> Dict[str, Any]:
    """Helper function to handle return data from Futu API
    
    Args:
        ret: Return code from Futu API
        data: Data returned from Futu API
    
    Returns:
        Dict containing either the data or error message
    """
    if ret != RET_OK:
        return {'error': str(data)}
    
    # If data is already a dict, return it directly
    if isinstance(data, dict):
        return data
    
    # If data has to_dict method, call it
    if hasattr(data, 'to_dict'):
        return data.to_dict()
    
    # If data is a pandas DataFrame, convert to dict
    if hasattr(data, 'to_dict') and callable(getattr(data, 'to_dict')):
        return data.to_dict('records')
    
    # For other types, try to convert to dict or return as is
    try:
        return dict(data)
    except (TypeError, ValueError):
        return {'data': data}

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
    
    Returns:
        Dict containing quote data including:
        - code: Stock code
        - name: Stock name
        - last_price: Latest price
        - open_price: Opening price
        - high_price: Highest price
        - low_price: Lowest price
        - volume: Trading volume
        - turnover: Trading amount
        - turnover_rate: Turnover rate
        - amplitude: Price amplitude
        - dark_status: Dark pool status
        - price_spread: Price spread
    """
    ret, data = quote_ctx.get_stock_quote(symbols)
    return handle_return_data(ret, data)

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
    
    Returns:
        Dict containing snapshot data including:
        - code: Stock code
        - update_time: Update time
        - last_price: Latest price
        - open_price: Opening price
        - high_price: Highest price
        - low_price: Lowest price
        - volume: Trading volume
        - turnover: Trading amount
        - turnover_rate: Turnover rate
        - suspension: Whether trading is suspended
        - listing_date: Listing date
        - price_spread: Price spread
        - lot_size: Lot size
        - ask/bid_price: First 10 ask/bid prices
        - ask/bid_volume: First 10 ask/bid volumes
    """
    ret, data = quote_ctx.get_market_snapshot(symbols)
    return handle_return_data(ret, data)

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
            - "K_QUARTER": Quarterly
            - "K_YEAR": Yearly
        count: Number of K-lines to return (default: 100)
            Range: 1-1000
    
    Returns:
        Dict containing K-line data including:
        - code: Stock code
        - time_key: K-line time (yyyy-MM-dd HH:mm:ss)
        - open: Opening price
        - close: Closing price
        - high: Highest price
        - low: Lowest price
        - volume: Trading volume
        - turnover: Trading amount
        - pe_ratio: Price-to-earnings ratio
        - turnover_rate: Turnover rate
        - change_rate: Price change rate
        - last_close: Last closing price
    """
    ret, data = quote_ctx.get_cur_kline(
        code=symbol,
        ktype=ktype,
        num=count
    )
    return handle_return_data(ret, data)

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
    
    Returns:
        Dict containing K-line data including:
        - code: Stock code
        - time_key: K-line time (yyyy-MM-dd HH:mm:ss)
        - open: Opening price
        - close: Closing price
        - high: Highest price
        - low: Lowest price
        - volume: Trading volume
        - turnover: Trading amount
        - pe_ratio: Price-to-earnings ratio
        - turnover_rate: Turnover rate
        - change_rate: Price change rate
        - last_close: Last closing price
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
    
    Returns:
        Dict containing real-time data including:
        - code: Stock code
        - time: Update time
        - data_status: Data status
        - price: Latest price
        - volume: Trading volume
        - turnover: Trading amount
        - avg_price: Average price
    """
    ret, data = quote_ctx.get_rt_data(symbol)
    return handle_return_data(ret, data)

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
    
    Returns:
        Dict containing ticker data including:
        - code: Stock code
        - time: Deal time
        - price: Deal price
        - volume: Deal volume
        - turnover: Deal amount
        - ticker_direction: Ticker direction
        - sequence: Sequence number
        - type: Ticker type
    """
    ret, data = quote_ctx.get_ticker(symbol)
    return handle_return_data(ret, data)

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
    
    Returns:
        Dict containing order book data including:
        - code: Stock code
        - svr_recv_time_bid: Server receive time for bid
        - svr_recv_time_ask: Server receive time for ask
        - Bid: List of bid data [(price, volume, order_count, {}), ...]
        - Ask: List of ask data [(price, volume, order_count, {}), ...]
    """
    ret, data = quote_ctx.get_order_book(symbol)
    return handle_return_data(ret, data)

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
    
    Returns:
        Dict containing broker queue data including:
        - code: Stock code
        - svr_recv_time_bid: Server receive time for bid
        - svr_recv_time_ask: Server receive time for ask
        - bid_broker_queue: List of bid brokers [(broker_id, broker_name, broker_pos), ...]
        - ask_broker_queue: List of ask brokers [(broker_id, broker_name, broker_pos), ...]
    """
    ret, data = quote_ctx.get_broker_queue(symbol)
    return handle_return_data(ret, data)

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
            - "K_3M": 3-minute K-line
            - "K_5M": 5-minute K-line
            - "K_15M": 15-minute K-line
            - "K_30M": 30-minute K-line
            - "K_60M": 60-minute K-line
            - "K_DAY": Daily K-line
            - "K_WEEK": Weekly K-line
            - "K_MON": Monthly K-line
            - "K_QUARTER": Quarterly K-line
            - "K_YEAR": Yearly K-line
    
    Note:
        - Maximum 100 symbols per request
        - Maximum 5 subscription types per request
        - Each socket can subscribe up to 500 symbols
    
    Returns:
        Dict containing subscription result:
        - status: "success" or error message
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
    
    Returns:
        Dict containing option chain data including:
        - code: Option code
        - name: Option name
        - owner_stock_code: Underlying stock code
        - strike_time: Strike time
        - strike_price: Strike price
        - suspension: Whether suspended
        - stock_id: Stock ID
        - lot_size: Lot size
        - option_type: Option type (Call/Put)
        - trade_time: Trading time
        - expiry_time: Expiry time
        - exercise_type: Exercise type (European/American)
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
    
    Returns:
        Dict containing expiration dates:
        - strike_time: List of expiration dates in format "YYYY-MM-DD"
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
    """Get account list"""
    if not init_trade_connection():
        return {'error': 'Failed to initialize trade connection'}
    ret, data = trade_ctx.get_acc_list()
    return handle_return_data(ret, data)

@mcp.tool()
async def get_funds() -> Dict[str, Any]:
    """Get account funds information"""
    if not init_trade_connection():
        return {'error': 'Failed to initialize trade connection'}
    try:
        ret, data = trade_ctx.accinfo_query()
        if ret != RET_OK:
            return {'error': str(data)}
        
        if data is None or data.empty:
            return {'error': 'No account information available'}
            
        return handle_return_data(ret, data)
    except Exception as e:
        return {'error': f'Failed to get account funds: {str(e)}'}

@mcp.tool()
async def get_positions() -> Dict[str, Any]:
    """Get account positions"""
    if not init_trade_connection():
        return {'error': 'Failed to initialize trade connection'}
    ret, data = trade_ctx.position_list_query()
    return handle_return_data(ret, data)

@mcp.tool()
async def get_max_power() -> Dict[str, Any]:
    """Get maximum trading power for the account"""
    if not init_trade_connection():
        return {'error': 'Failed to initialize trade connection'}
    ret, data = trade_ctx.get_max_power()
    return handle_return_data(ret, data)

@mcp.tool()
async def get_margin_ratio(symbol: str) -> Dict[str, Any]:
    """Get margin ratio for a security"""
    if not init_trade_connection():
        return {'error': 'Failed to initialize trade connection'}
    ret, data = trade_ctx.get_margin_ratio(symbol)
    return handle_return_data(ret, data)

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
    
    Returns:
        Dict containing market state information including:
        - market: Market code
        - market_state: Market state
            - NONE: Market not available
            - AUCTION: Auction period
            - WAITING_OPEN: Waiting for market open
            - MORNING: Morning session
            - REST: Lunch break
            - AFTERNOON: Afternoon session
            - CLOSED: Market closed
            - PRE_MARKET_BEGIN: Pre-market begin
            - PRE_MARKET_END: Pre-market end
            - AFTER_HOURS_BEGIN: After-hours begin
            - AFTER_HOURS_END: After-hours end
        - begin_time: State begin time
        - end_time: State end time
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

if __name__ == "__main__":
    try:
        # 清理旧的进程和文件
        cleanup_stale_processes()
        
        # 获取锁
        lock_fd = acquire_lock()
        if lock_fd is None:
            logger.error("Failed to acquire lock. Another instance may be running.")
            sys.exit(1)
            
        # 设置信号处理
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
            
        logger.info("Initializing Futu connection...")
        if init_futu_connection():
            logger.info("Successfully initialized Futu connection")
            logger.info("Starting MCP server in stdio mode...")
            try:
                mcp.run(transport='stdio')
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, shutting down...")
                sys.exit(0)
            except Exception as e:
                logger.error(f"Error running server: {str(e)}")
                sys.exit(1)
        else:
            logger.error("Failed to initialize Futu connection. Server will not start.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}")
        sys.exit(1)
    finally:
        cleanup_all() 