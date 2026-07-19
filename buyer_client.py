import os
import compat
import asyncio
from dotenv import load_dotenv
from eth_account import Account


from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client
from x402.mechanisms.svm import KeypairSigner
from x402.mechanisms.svm.exact.register import register_exact_svm_client
from x402.mechanisms.tvm import TVM_MAINNET, WalletV5R1Config, WalletV5R1MnemonicSigner
from x402.mechanisms.tvm.exact import ExactTvmClientScheme

load_dotenv()
async def main():
    client=x402Client()

    account=Account.from_key(os.getenv("EVM_PRIVATE_KEY"))
    register_exact_evm_client(client, EthAccountSigner(account))

    svm_signer=KeypairSigner.from_base58(os.getenv("SVM_PRIVATE_KEY"))
    register_exact_svm_client(client, svm_signer)

    async with x402HttpxClient(client) as http:
        response =await http.get("http://127.0.0.1:8000/weather")
        print(f"Response: {response.text}")


asyncio.run(main())
