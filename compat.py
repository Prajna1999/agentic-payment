# ponytail: shims solana 0.40.x (dropped sync Client + TxOpts) for x402 compat
import sys
import asyncio
from types import ModuleType


def _patch_solana():
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.models import TxOpts
    import solana.rpc.types as _types

    # Patch TxOpts into solana.rpc.types
    if not hasattr(_types, "TxOpts"):
        _types.TxOpts = TxOpts

    # Inject solana.rpc.api with a sync Client shim
    if "solana.rpc.api" not in sys.modules:
        class Client:
            def __init__(self, endpoint, *args, **kwargs):
                self._async = AsyncClient(endpoint, *args, **kwargs)

            def _run(self, coro):
                return asyncio.run(coro)

            def simulate_transaction(self, txn, **kwargs):
                return self._run(self._async.simulate_transaction(txn, **kwargs))

            def send_raw_transaction(self, txn, **kwargs):
                return self._run(self._async.send_raw_transaction(txn, **kwargs))

            def get_signature_statuses(self, sigs, **kwargs):
                return self._run(self._async.get_signature_statuses(sigs, **kwargs))

        mod = ModuleType("solana.rpc.api")
        mod.Client = Client
        sys.modules["solana.rpc.api"] = mod


_patch_solana()
