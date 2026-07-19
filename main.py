import os
import json
import base64
import logging
from datetime import datetime, timezone
import compat  # noqa: F401 — must run before x402 SVM imports
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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

transactions: list[dict] = []


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
                log.info(f"Recept header,{receipt_header} ")
                if receipt_header:
                    try:
                        receipt = json.loads(base64.b64decode(receipt_header))
                        log.info(f'Post decode {receipt}')
                        network = receipt.get("network", "?")
                        tx = {
                            "time": datetime.now(timezone.utc).isoformat(),
                            "network": network,
                            "tx": receipt.get("transaction") or receipt.get("txHash", "?"),
                            "amount": network_price.get(network, "?"),
                            "payer": receipt.get("payer", "?"),
                        }
                        transactions.append(tx)
                        log.info("💸 Payment settled | %s", tx)
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

# network → price lookup built from routes
network_price: dict[str, str] = {
    opt.network: opt.price
    for route in routes.values()
    for opt in route.accepts
}

app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
app.add_middleware(PaymentLogger)  # outermost: sees response after PaymentMiddlewareASGI sets headers


@app.get("/weather")
async def get_weather():
    return {"weather": "sunny", "temperature": 70}


@app.get("/transactions")
async def get_transactions():
    return transactions


@app.post("/buy")
async def trigger_buy():
    from buyer_client import buy
    try:
        result = await buy()
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    evm_explorer = "https://sepolia.basescan.org/tx"
    svm_explorer = "https://explorer.solana.com/tx"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>x402 Payment Dashboard</title>
  <style>
    body {{ font-family: monospace; max-width: 800px; margin: 40px auto; padding: 0 20px; background: #0f0f0f; color: #e0e0e0; }}
    h1 {{ color: #fff; border-bottom: 1px solid #333; padding-bottom: 12px; }}
    button {{ background: #1a1a2e; color: #7eb8f7; border: 1px solid #7eb8f7; padding: 10px 24px; cursor: pointer; font-family: monospace; font-size: 14px; border-radius: 4px; }}
    button:hover {{ background: #7eb8f7; color: #0f0f0f; }}
    button:disabled {{ opacity: 0.4; cursor: not-allowed; }}
    #result {{ margin: 16px 0; padding: 12px; background: #1a1a1a; border-left: 3px solid #7eb8f7; display: none; white-space: pre; }}
    #result.error {{ border-color: #f77e7e; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
    th {{ text-align: left; padding: 8px; border-bottom: 1px solid #333; color: #888; font-weight: normal; }}
    td {{ padding: 8px; border-bottom: 1px solid #1e1e1e; font-size: 13px; }}
    td a {{ color: #7eb8f7; text-decoration: none; }}
    td a:hover {{ text-decoration: underline; }}
    .empty {{ color: #555; padding: 16px 0; }}
    .tag {{ font-size: 11px; padding: 2px 6px; border-radius: 3px; background: #1a1a2e; color: #7eb8f7; }}
  </style>
</head>
<body>
  <h1>x402 Payment Dashboard</h1>

  <button id="btn" onclick="triggerBuy()">Buy Weather Report ($0.001)</button>
  <div id="result"></div>

  <h2 style="margin-top:40px; font-size:16px; color:#888;">Transaction History</h2>
  <table>
    <thead><tr><th>Time</th><th>Network</th><th>Amount</th><th>Payer</th><th>Tx</th></tr></thead>
    <tbody id="txs"><tr><td colspan="5" class="empty">No transactions yet.</td></tr></tbody>
  </table>

  <script>
    async function triggerBuy() {{
      const btn = document.getElementById('btn');
      const res = document.getElementById('result');
      btn.disabled = true;
      btn.textContent = 'Processing...';
      res.style.display = 'none';
      try {{
        const r = await fetch('/buy', {{method: 'POST'}});
        const d = await r.json();
        res.style.display = 'block';
        if (d.ok) {{
          res.className = '';
          res.textContent = JSON.stringify(d.data, null, 2);
        }} else {{
          res.className = 'error';
          res.textContent = 'Error: ' + d.error;
        }}
      }} catch(e) {{
        res.style.display = 'block';
        res.className = 'error';
        res.textContent = 'Error: ' + e.message;
      }}
      btn.disabled = false;
      btn.textContent = 'Buy Weather Report ($0.001)';
    }}

    function explorerLink(network, tx) {{
      if (!tx || tx === '?') return tx;
      const short = tx.slice(0, 10) + '...' + tx.slice(-6);
      const base = network.startsWith('solana')
        ? '{svm_explorer}/' + tx + '?cluster=devnet'
        : '{evm_explorer}/' + tx;
      return '<a href="' + base + '" target="_blank">' + short + '</a>';
    }}

    async function pollTxs() {{
      const r = await fetch('/transactions');
      const txs = await r.json();
      const tbody = document.getElementById('txs');
      if (!txs.length) return;
      tbody.innerHTML = txs.slice().reverse().map(t => `
        <tr>
          <td>${{new Date(t.time).toLocaleTimeString()}}</td>
          <td><span class="tag">${{t.network}}</span></td>
          <td>${{t.amount}}</td>
          <td>${{t.payer ? t.payer.slice(0,8)+'...' : '?'}}</td>
          <td>${{explorerLink(t.network, t.tx)}}</td>
        </tr>`).join('');
    }}

    pollTxs();
    setInterval(pollTxs, 3000);
  </script>
</body>
</html>"""

