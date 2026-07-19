# x402 Payment Flow — Setup Guide

## 1. Generate Wallets

Run once to create your EVM and Solana keypairs:

```bash
uv run python -c "
from eth_account import Account
from solders.keypair import Keypair

evm = Account.create()
print('EVM address:    ', evm.address)
print('EVM private key:', evm.key.hex())

svm = Keypair()
print('SVM address:    ', svm.pubkey())
print('SVM private key:', svm)
"
```

Save both addresses and private keys — you won't see them again.

---

## 2. Fund the Wallets

You need two things per chain: **gas** (to pay for transactions) and **USDC** (the payment token).

### Base Sepolia (EVM)

| What | Where | Notes |
|------|-------|-------|
| Sepolia ETH (gas) | https://www.alchemy.com/faucets/base-sepolia | Free, requires login |
| Testnet USDC | https://faucet.circle.com | Select **Base Sepolia** |

### Solana Devnet (SVM)

| What | Where | Notes |
|------|-------|-------|
| Devnet SOL (gas) | https://faucet.solana.com | Select **Devnet** |
| Testnet USDC | https://faucet.circle.com | Select **Solana Devnet** |

---

## 3. Configure Environment

Create a `.env` file in the project root:

```
EVM_ADDRESS=<your EVM address>
EVM_PRIVATE_KEY=<your EVM private key>
SVM_ADDRESS=<your Solana address>
SVM_PRIVATE_KEY=<your Solana private key>
```

---

## 4. Run the Payment Flow

**Terminal 1 — start the seller server:**
```bash
uv run uvicorn main:app --port 8000
```

**Terminal 2 — run the buyer:**
```bash
uv run python buyer_client.py
```

### What happens

1. Buyer hits `GET /weather` → server returns **402 Payment Required** with a signed payment menu (EVM + SVM options)
2. Buyer picks a network, constructs a signed payment proof, replays the request with an `x-payment` header
3. Server sends proof to the x402 facilitator (`x402.org/facilitator`) for **verification**
4. Facilitator settles the USDC transfer on-chain and returns a receipt
5. Server logs the settlement and returns the weather data to the buyer

---

## 5. Verify the Transfer

After a successful payment, the server logs a tx hash:

```
💸 Payment settled | raw: {'txHash': '0xabc...', 'network': 'eip155:84532', ...}
```

Paste the hash into the relevant explorer:

- **EVM:** https://sepolia.basescan.org/tx/`<hash>`
- **SVM:** https://explorer.solana.com/tx/`<hash>`?cluster=devnet

You'll see the USDC moving from the buyer's wallet to the seller's wallet on-chain.

---

## Testnet → Mainnet

| Setting | Testnet | Mainnet |
|---------|---------|---------|
| Facilitator URL | `https://x402.org/facilitator` | `https://api.cdp.coinbase.com/platform/v2/x402` |
| EVM network | `eip155:84532` (Base Sepolia) | `eip155:8453` (Base) |
| SVM network | `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` (devnet) | `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp` (mainnet) |
