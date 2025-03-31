# Futu Stock MCP Server

A Model Context Protocol (MCP) server for accessing Futu OpenAPI functionality.

## Features

- Standard MCP 2.0 protocol compliance
- Comprehensive Futu API coverage
- Real-time data subscription support
- Market data access
- Derivatives information
- Account query capabilities
- Resource-based data access
- Interactive prompts for analysis

## Prerequisites

- Python 3.10+
- Futu OpenAPI SDK
- Model Context Protocol SDK
- uv (recommended)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/futu-stock-mcp-server.git
cd futu-stock-mcp-server
```

2. Install uv:
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

3. Create and activate a virtual environment:
```bash
# Create virtual environment
uv venv

# Activate virtual environment
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate
```

4. Install dependencies:
```bash
# Install in editable mode
uv pip install -e .
```

5. Copy the environment file and configure:
```bash
cp .env.example .env
```

Edit the `.env` file with your server settings:
```
HOST=0.0.0.0
PORT=8000
FUTU_HOST=127.0.0.1
FUTU_PORT=11111
```

## Development

### Managing Dependencies

Add new dependencies to `pyproject.toml`:
```toml
[project]
dependencies = [
    # ... existing dependencies ...
    "new-package>=1.0.0",
]
```

Then update your environment:
```bash
uv pip install -e .
```

### Code Style

This project uses Ruff for code linting and formatting. The configuration is in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py38"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "B", "UP"]
```

Run linting:
```bash
uv pip install ruff
ruff check .
```

Run formatting:
```bash
ruff format .
```

## Usage

1. Start the server:
```bash
python -m futu_stock_mcp_server.server
```

2. Connect to the server using an MCP client:
```python
from modelcontextprotocol import ClientSession, StdioServerParameters
from modelcontextprotocol.client.stdio import stdio_client

async def main():
    server_params = StdioServerParameters(
        command="python",
        args=["src/server.py"]
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            
            # Call a tool
            result = await session.call_tool(
                "get_stock_quote",
                arguments={"symbols": ["HK.00700"]}
            )
            
            # Access a resource
            content, mime_type = await session.read_resource(
                "market://HK.00700"
            )
            
            # Get a prompt
            prompt = await session.get_prompt(
                "market_analysis",
                arguments={"symbol": "HK.00700"}
            )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Available API Methods

### Market Data Tools
- `get_stock_quote`: Get stock quote data
- `get_market_snapshot`: Get market snapshot
- `get_cur_kline`: Get current K-line data
- `get_history_kline`: Get historical K-line data
- `get_rt_data`: Get real-time data
- `get_ticker`: Get ticker data
- `get_order_book`: Get order book data
- `get_broker_queue`: Get broker queue data

### Subscription Tools
- `subscribe`: Subscribe to real-time data
- `unsubscribe`: Unsubscribe from real-time data

### Derivatives Tools
- `get_option_chain`: Get option chain data
- `get_option_expiration_date`: Get option expiration dates
- `get_option_condor`: Get option condor strategy data
- `get_option_butterfly`: Get option butterfly strategy data

### Account Query Tools
- `get_account_list`: Get account list
- `get_asset_info`: Get asset information
- `get_asset_allocation`: Get asset allocation information

### Market Information Tools
- `get_market_state`: Get market state
- `get_security_info`: Get security information
- `get_security_list`: Get security list

## Resources

### Market Data
- `market://{symbol}`: Get market data for a symbol
- `kline://{symbol}/{ktype}`: Get K-line data for a symbol

## Prompts

### Analysis
- `market_analysis`: Create a market analysis prompt
- `option_strategy`: Create an option strategy analysis prompt

## Error Handling

The server follows the MCP 2.0 error response format:

```json
{
    "jsonrpc": "2.0",
    "id": "request_id",
    "error": {
        "code": -32000,
        "message": "Error message",
        "data": null
    }
}
```

## Security

- The server uses secure WebSocket connections
- All API calls are authenticated through the Futu OpenAPI
- Environment variables are used for sensitive configuration

## Development

### Adding New Tools

To add a new tool, use the `@mcp.tool()` decorator:

```python
@mcp.tool()
async def new_tool(param1: str, param2: int) -> Dict[str, Any]:
    """Tool description"""
    # Implementation
    return result
```

### Adding New Resources

To add a new resource, use the `@mcp.resource()` decorator:

```python
@mcp.resource("resource://{param1}/{param2}")
async def new_resource(param1: str, param2: str) -> Dict[str, Any]:
    """Resource description"""
    # Implementation
    return result
```

### Adding New Prompts

To add a new prompt, use the `@mcp.prompt()` decorator:

```python
@mcp.prompt()
async def new_prompt(param1: str) -> str:
    """Prompt description"""
    return f"Prompt template with {param1}"
```

## License

MIT License 