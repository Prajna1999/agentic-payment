import os
import compat  # noqa: F401 — must run before x402 SVM imports
from fastapi import FastAPI
from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.mechanisms.svm.exact import ExactSvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

app = FastAPI()

EVM_ADDRESS = "0x..."
SVM_ADDRESS = "0x...."
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


@app.get("/weather")
async def get_weather():
    return {"weather": "sunny", "temperature": 70}

