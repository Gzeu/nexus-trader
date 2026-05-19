# Binance Testnet API Keys — How to Get Them

## Spot Testnet
1. Go to https://testnet.binance.vision/
2. Click **"Log In with GitHub"**
3. Click **"Generate HMAC_SHA256 Key"**
4. Copy `API Key` and `Secret Key` into `.env`:

```env
BINANCE_API_KEY=your_testnet_key_here
BINANCE_API_SECRET=your_testnet_secret_here
TESTNET=true
DRY_RUN=true
```

## Futures Testnet
1. Go to https://testnet.binancefuture.com/
2. Register / login
3. API Management → Create Key
4. If using separate keys for futures, set in `.env`:

```env
BINANCE_FUTURES_API_KEY=your_futures_testnet_key
BINANCE_FUTURES_API_SECRET=your_futures_testnet_secret
```

> If `BINANCE_FUTURES_API_KEY` is empty, the backend falls back to
> `BINANCE_API_KEY` / `BINANCE_API_SECRET` for both spot and futures.

## Testnet Limitations
- Testnet resets balances periodically (usually weekly)
- Not all symbols available — `BTCUSDT`, `ETHUSDT`, `BNBUSDT` always work
- Testnet latency is higher than mainnet — normal
- Rate limits are more relaxed than mainnet

## Verify Connection
```bash
source .venv/bin/activate
python3 - <<'EOF'
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from backend.binance.binance_client import BinanceClient
from backend.config import get_settings

async def test():
    cfg = get_settings()
    async with BinanceClient(cfg) as client:
        info = await client.get_spot_account()
        print("Connected! Balances:", [
            b for b in info.get('balances', [])
            if float(b['free']) > 0
        ][:5])
asyncio.run(test())
EOF
```
