# -*- coding: utf-8 -*-

import asyncio

import uvicorn


async def main():
    config = uvicorn.Config(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
