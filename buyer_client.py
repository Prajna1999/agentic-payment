import os
import compat  # noqa: F401
from dotenv import load_dotenv
from eth_account import Account
from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client
from x402.mechanisms.svm import KeypairSigner
from x402.mechanisms.svm.exact.register import register_exact_svm_client

load_dotenv()


async def buy(url: str = "http://127.0.0.1:8000/weather") -> dict:
    client = x402Client()
    register_exact_evm_client(client, EthAccountSigner(Account.from_key(os.getenv("EVM_PRIVATE_KEY"))))
    register_exact_svm_client(client, KeypairSigner.from_base58(os.getenv("SVM_PRIVATE_KEY")))
    async with x402HttpxClient(client) as http:
        response = await http.get(url)
        return response.json()


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(buy()))
