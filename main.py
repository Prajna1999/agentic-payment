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

        # capture x-payment header from request
        req_headers = dict(scope.get("headers", []))
        x_payment_raw = req_headers.get(b"x-payment", b"").decode()
        x_payment_decoded = None
        if x_payment_raw:
            try:
                x_payment_decoded = json.loads(base64.b64decode(x_payment_raw))
            except Exception:
                x_payment_decoded = x_payment_raw

        async def send_with_log(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                receipt_header = headers.get(b"payment-response", b"").decode()
                payment_req_header = headers.get(b"payment-required", b"").decode()
                if receipt_header:
                    try:
                        receipt = json.loads(base64.b64decode(receipt_header))
                        network = receipt.get("network", "?")
                        tx = {
                            "time": datetime.now(timezone.utc).isoformat(),
                            "network": network,
                            "tx": receipt.get("transaction") or receipt.get("txHash", "?"),
                            "amount": network_price.get(network, "?"),
                            "payer": receipt.get("payer", "?"),
                            "headers": {
                                "x_payment": x_payment_decoded,
                                "payment_response": receipt,
                            },
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


@app.get("/generate-wallet")
async def generate_wallet():
    from eth_account import Account
    acct = Account.create()
    return {"address": acct.address, "private_key": acct.key.hex()}


@app.get("/payment-meta")
async def payment_meta():
    """Returns what the 402 payment-required header contains, decoded."""
    return {
        "x402Version": 2,
        "error": "Payment required",
        "resource": {"url": "http://localhost:8000/weather", "mimeType": "application/json", "description": "Weather report"},
        "accepts": [
            {"scheme": o.scheme, "network": o.network, "price": o.price, "payTo": o.pay_to}
            for route in routes.values() for o in route.accepts
        ],
    }


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
    * {{ box-sizing: border-box; }}
    body {{ font-family: monospace; max-width: 860px; margin: 40px auto; padding: 0 24px; background: #0f0f0f; color: #e0e0e0; }}
    h1 {{ color: #fff; border-bottom: 1px solid #333; padding-bottom: 12px; margin-bottom: 28px; }}
    h2 {{ font-size: 13px; color: #555; text-transform: uppercase; letter-spacing: 1px; margin: 40px 0 12px; }}
    button {{ background: #1a1a2e; color: #7eb8f7; border: 1px solid #7eb8f7; padding: 10px 24px; cursor: pointer; font-family: monospace; font-size: 14px; border-radius: 4px; }}
    button:hover {{ background: #7eb8f7; color: #0f0f0f; }}
    button:disabled {{ opacity: 0.4; cursor: not-allowed; }}
    #result {{ margin: 16px 0; padding: 12px; background: #1a1a1a; border-left: 3px solid #7eb8f7; display: none; white-space: pre; font-size: 13px; }}
    #result.error {{ border-color: #f77e7e; }}

    /* stepper */
    #flow {{ display: none; margin: 24px 0; }}
    .flow-row {{ display: flex; align-items: flex-start; gap: 12px; margin-bottom: 4px; }}
    .flow-line {{ display: flex; flex-direction: column; align-items: center; width: 24px; flex-shrink: 0; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; background: #2a2a2a; border: 2px solid #333; margin-top: 4px; transition: all 0.3s; flex-shrink: 0; }}
    .dot.active {{ background: #7eb8f7; border-color: #7eb8f7; box-shadow: 0 0 6px #7eb8f7; }}
    .dot.done {{ background: #4caf82; border-color: #4caf82; }}
    .dot.error {{ background: #f77e7e; border-color: #f77e7e; }}
    .connector {{ width: 2px; height: 20px; background: #222; margin: 2px 0; transition: background 0.3s; }}
    .connector.done {{ background: #4caf82; }}
    .step-text {{ padding: 2px 0; font-size: 13px; color: #444; transition: color 0.3s; line-height: 1.4; }}
    .step-text .label {{ display: block; }}
    .step-text .sub {{ font-size: 11px; color: #333; transition: color 0.3s; }}
    .flow-row.active .step-text {{ color: #e0e0e0; }}
    .flow-row.active .step-text .sub {{ color: #7eb8f7; }}
    .flow-row.done .step-text {{ color: #777; }}
    .flow-row.done .step-text .sub {{ color: #4caf82; }}
    .flow-row.error .step-text {{ color: #f77e7e; }}

    /* who label */
    .who {{ font-size: 10px; padding: 1px 5px; border-radius: 2px; margin-left: 6px; vertical-align: middle; }}
    .who.buyer {{ background: #1a2a1a; color: #4caf82; }}
    .who.server {{ background: #1a1a2e; color: #7eb8f7; }}
    .who.facilitator {{ background: #2a1a2a; color: #c77ef7; }}
    .who.chain {{ background: #2a2010; color: #f7c97e; }}

    details {{ margin: 6px 0 0 0; }}
    summary {{ font-size: 11px; color: #555; cursor: pointer; user-select: none; }}
    summary:hover {{ color: #888; }}
    .hdr-box {{ margin-top: 6px; background: #141414; border: 1px solid #2a2a2a; border-radius: 3px; padding: 10px 12px; font-size: 11px; line-height: 1.6; white-space: pre-wrap; color: #aaa; max-height: 200px; overflow-y: auto; }}
    .hdr-box .key {{ color: #7eb8f7; }}
    .hdr-box .val {{ color: #c8e6c9; }}
    .hdr-box .dim {{ color: #555; }}

    /* tabs */
    .tabs {{ display: flex; gap: 0; border-bottom: 1px solid #333; margin-bottom: 28px; }}
    .tab {{ padding: 8px 20px; cursor: pointer; font-size: 13px; color: #555; border-bottom: 2px solid transparent; margin-bottom: -1px; }}
    .tab:hover {{ color: #aaa; }}
    .tab.active {{ color: #7eb8f7; border-bottom-color: #7eb8f7; }}
    .panel {{ display: none; }}
    .panel.active {{ display: block; }}

    /* wallet */
    .field-label {{ font-size: 11px; color: #555; text-transform: uppercase; letter-spacing: 1px; margin: 20px 0 6px; }}
    .field-val {{ background: #141414; border: 1px solid #2a2a2a; border-radius: 3px; padding: 10px 12px; font-size: 13px; word-break: break-all; color: #e0e0e0; position: relative; }}
    .copy-btn {{ position: absolute; right: 8px; top: 8px; background: none; border: 1px solid #333; color: #555; font-size: 11px; padding: 2px 7px; cursor: pointer; border-radius: 3px; }}
    .copy-btn:hover {{ color: #aaa; border-color: #555; }}
    .warning {{ margin-top: 16px; padding: 10px 12px; border-left: 3px solid #f7c97e; background: #1a160a; font-size: 12px; color: #f7c97e; }}
    .note {{ font-size: 12px; color: #555; margin-top: 10px; }}

    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; padding: 8px; border-bottom: 1px solid #222; color: #555; font-weight: normal; font-size: 12px; }}
    td {{ padding: 8px; border-bottom: 1px solid #1a1a1a; font-size: 13px; }}
    td a {{ color: #7eb8f7; text-decoration: none; }}
    td a:hover {{ text-decoration: underline; }}
    .empty {{ color: #444; }}
    .tag {{ font-size: 11px; padding: 2px 6px; border-radius: 3px; background: #1a1a2e; color: #7eb8f7; }}
  </style>
</head>
<body>
  <h1>x402 Payment Dashboard</h1>

  <div class="tabs">
    <div class="tab active" onclick="switchTab('dashboard')">Dashboard</div>
    <div class="tab" onclick="switchTab('wallet')">Create Wallet</div>
  </div>

  <!-- Dashboard panel -->
  <div class="panel active" id="panel-dashboard">
    <button id="btn" onclick="triggerBuy()">Buy Weather Report ($0.001 USDC)</button>

    <div id="flow">
      <h2>Payment Flow</h2>
    </div>

    <div id="result"></div>

    <h2>Transaction History</h2>
    <table>
      <thead><tr><th>Time</th><th>Network</th><th>Amount</th><th>Payer</th><th>Tx</th></tr></thead>
      <tbody id="txs"><tr><td colspan="5" class="empty">No transactions yet.</td></tr></tbody>
    </table>
  </div>

  <!-- Wallet panel -->
  <div class="panel" id="panel-wallet">
    <p style="color:#888;font-size:13px;">Generate a new EVM keypair. The private key is shown once — save it somewhere safe.</p>
    <button onclick="generateWallet()">Generate New Wallet</button>

    <div id="wallet-result" style="display:none">
      <div class="field-label">Address (public)</div>
      <div class="field-val" id="w-address">
        <button class="copy-btn" onclick="copy('w-address')">copy</button>
        <span id="w-address-val"></span>
      </div>

      <div class="field-label">Private Key — keep secret</div>
      <div class="field-val" id="w-key" style="border-color:#4a2a2a">
        <button class="copy-btn" onclick="copy('w-key')">copy</button>
        <span id="w-key-val"></span>
      </div>

      <div class="warning">Never share your private key. Anyone with it controls your funds.</div>

      <div class="note">
        Fund this address with testnet USDC at
        <a href="https://faucet.circle.com" target="_blank" style="color:#7eb8f7">faucet.circle.com</a>
        (select Base Sepolia), and Sepolia ETH for gas at
        <a href="https://www.alchemy.com/faucets/base-sepolia" target="_blank" style="color:#7eb8f7">Alchemy faucet</a>.
      </div>
    </div>
  </div>

  <script>
    const STEPS = [
      {{ label: 'Requesting resource',          sub: 'GET /weather → server',                       who: 'buyer',       headerKey: null }},
      {{ label: '402 Payment Required',          sub: 'Server returns payment menu (EVM + SVM)',     who: 'server',      headerKey: 'payment_required' }},
      {{ label: 'Signing payment authorization', sub: 'EIP-3009 off-chain signature (no gas)',       who: 'buyer',       headerKey: null }},
      {{ label: 'Sending payment proof',         sub: 'Replaying GET with x-payment header',         who: 'buyer',       headerKey: 'x_payment' }},
      {{ label: 'Facilitator verifying',         sub: 'Checking signature & authorization on-chain', who: 'facilitator', headerKey: null }},
      {{ label: 'Settling on-chain',             sub: 'transferWithAuthorization → USDC moves',      who: 'chain',       headerKey: null }},
      {{ label: 'Resource delivered',            sub: 'Server returns weather data + receipt',       who: 'server',      headerKey: 'payment_response' }},
    ];

    const DELAYS = [300, 400, 600, 300, 700, 800, 200];
    let flowHeaders = {{}};

    function jsonHtml(obj) {{
      const s = JSON.stringify(obj, null, 2);
      return s.replace(/"([^"]+)":/g, '<span class="key">"$1"</span>:')
              .replace(/: "([^"]+)"/g, ': <span class="val">"$1"</span>')
              .replace(/: (true|false|null|\d+)/g, ': <span class="dim">$1</span>');
    }}

    function buildFlow() {{
      const flow = document.getElementById('flow');
      flow.innerHTML = '<h2>Payment Flow</h2>';
      STEPS.forEach((s, i) => {{
        const isLast = i === STEPS.length - 1;
        const hdr = s.headerKey && flowHeaders[s.headerKey];
        const detailsHtml = hdr
          ? `<details><summary>view header ↓</summary><div class="hdr-box">${{jsonHtml(hdr)}}</div></details>`
          : '';
        flow.innerHTML += `
          <div class="flow-row" id="step-${{i}}">
            <div class="flow-line">
              <div class="dot" id="dot-${{i}}"></div>
              ${{!isLast ? '<div class="connector" id="conn-' + i + '"></div>' : ''}}
            </div>
            <div class="step-text">
              <span class="label">${{s.label}}<span class="who ${{s.who}}">${{s.who}}</span></span>
              <span class="sub">${{s.sub}}</span>
              ${{detailsHtml}}
            </div>
          </div>`;
      }});
    }}

    function setStep(i, state) {{
      const row = document.getElementById('step-' + i);
      const dot = document.getElementById('dot-' + i);
      const conn = document.getElementById('conn-' + i);
      row.className = 'flow-row ' + state;
      dot.className = 'dot ' + state;
      if (conn && state === 'done') conn.className = 'connector done';
    }}

    function sleep(ms) {{ return new Promise(r => setTimeout(r, ms)); }}

    async function animateSteps(fetchPromise) {{
      // animate steps 0-4 while fetch is in flight
      for (let i = 0; i < 5; i++) {{
        setStep(i, 'active');
        await sleep(DELAYS[i]);
        setStep(i, 'done');
      }}
      // step 5 (settle) stays active until fetch resolves
      setStep(5, 'active');
      const result = await fetchPromise;
      setStep(5, result.ok ? 'done' : 'error');
      await sleep(DELAYS[5]);
      setStep(6, result.ok ? 'active' : 'error');
      if (result.ok) {{ await sleep(DELAYS[6]); setStep(6, 'done'); }}
      return result;
    }}

    async function triggerBuy() {{
      const btn = document.getElementById('btn');
      const res = document.getElementById('result');
      btn.disabled = true;
      btn.textContent = 'Processing...';
      res.style.display = 'none';
      document.getElementById('flow').style.display = 'block';

      // pre-load the 402 header payload
      const meta = await fetch('/payment-meta').then(r => r.json());
      flowHeaders = {{ payment_required: meta }};
      buildFlow();

      const fetchPromise = fetch('/buy', {{method: 'POST'}}).then(r => r.json());
      const d = await animateSteps(fetchPromise);

      // inject live headers from last transaction and rebuild steps
      if (d.ok) {{
        const txs = await fetch('/transactions').then(r => r.json());
        const last = txs[txs.length - 1];
        if (last?.headers) {{
          flowHeaders = {{ ...flowHeaders, ...last.headers }};
          buildFlow();
          // restore done state on all steps
          STEPS.forEach((_, i) => setStep(i, 'done'));
        }}
      }}

      res.style.display = 'block';
      if (d.ok) {{
        res.className = '';
        res.textContent = JSON.stringify(d.data, null, 2);
      }} else {{
        res.className = 'error';
        res.textContent = 'Error: ' + d.error;
      }}
      btn.disabled = false;
      btn.textContent = 'Buy Weather Report ($0.001 USDC)';
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

    function switchTab(name) {{
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      document.getElementById('panel-' + name).classList.add('active');
      event.target.classList.add('active');
    }}

    async function generateWallet() {{
      const r = await fetch('/generate-wallet');
      const w = await r.json();
      document.getElementById('w-address-val').textContent = w.address;
      document.getElementById('w-key-val').textContent = w.private_key;
      document.getElementById('wallet-result').style.display = 'block';
    }}

    function copy(containerId) {{
      const text = document.getElementById(containerId + '-val').textContent;
      navigator.clipboard.writeText(text);
      const btn = document.querySelector('#' + containerId + ' .copy-btn');
      btn.textContent = 'copied!';
      setTimeout(() => btn.textContent = 'copy', 1500);
    }}
  </script>
</body>
</html>"""

