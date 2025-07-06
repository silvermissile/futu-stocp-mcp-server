from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

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