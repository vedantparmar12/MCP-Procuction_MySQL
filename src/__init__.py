import asyncio
import sys

# Set Windows event loop policy for aiomysql compatibility
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())