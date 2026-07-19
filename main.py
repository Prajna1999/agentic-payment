import os
import json
import base64
import logging
import compat  # noqa: F401 — must run before x402 SVM imports
from dotenv import load_dotenv
from fastapi import FastAPI
from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.mechanisms.svm.exact import ExactSvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("x402")
load_dotenv()
app = FastAPI()


class PaymentLogger:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_log(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                receipt_header = headers.get(b"payment-response", b"").decode()
                if receipt_header:
                    try:
                        receipt = json.loads(base64.b64decode(receipt_header))
                        log.info("💸 Payment settled | raw: %s", receipt)
                    except Exception:
                        log.info("💸 Payment settled | raw: %s", receipt_header[:120])
            await send(message)

        await self.app(scope, receive, send_with_log)

EVM_ADDRESS = os.getenv("EVM_ADDRESS")
SVM_ADDRESS = os.getenv("SVM_ADDRESS")
EVM_NETWORK: Network = "eip155:84532"  # ponytail: Base Sepolia; swap to eip155:8453 for mainnet
SVM_NETWORK: Network = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"  # ponytail: Solana devnet; swap to solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp for mainnet

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url="https://x402.org/facilitator"))

server = x402ResourceServer(facilitator)
server.register(EVM_NETWORK, ExactEvmServerScheme())
server.register(SVM_NETWORK, ExactSvmServerScheme())

routes: dict[str, RouteConfig] = {
    "GET /weather": RouteConfig(
        accepts=[
            PaymentOption(scheme="exact", pay_to=EVM_ADDRESS, price="$0.001", network=EVM_NETWORK),
            PaymentOption(scheme="exact", pay_to=SVM_ADDRESS, price="$0.001", network=SVM_NETWORK),
        ],
        mime_type="application/json",
        description="Weather report",
    ),
}

app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
app.add_middleware(PaymentLogger)  # outermost: sees response after PaymentMiddlewareASGI sets headers


@app.get("/weather")
async def get_weather():
    return {"weather": "sunny", "temperature": 70}

