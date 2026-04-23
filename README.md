# TW Stock Live Dashboard

This project is a Streamlit app for monitoring Taiwan stocks with:

- five-level bid/ask order book
- latest trade summary
- recent live trade tape

It is designed to be stored on GitHub and deployed with Streamlit Community Cloud.

## Stack

- UI: `Streamlit`
- Live market data: `Fugle MarketData WebSocket API`
- Deployment: `GitHub` + `Streamlit Community Cloud`

## Why this approach

True real-time Taiwan stock order-book and tick data is not a free public data feed. TWSE and TPEx both document their real-time market-data products and licensing. For a practical developer workflow, this starter app uses Fugle's official developer API, which provides:

- `books` channel for five-level bid/ask data
- `trades` channel for live trade updates

## Run locally

1. Install dependencies

```bash
pip install -r requirements.txt
```

2. Create `.streamlit/secrets.toml`

```toml
FUGLE_API_KEY = "your_fugle_api_key"
```

3. Start the app

```bash
streamlit run app.py
```

If no API key is configured, the app falls back to demo data so the UI can still be previewed.

## Deploy to Streamlit Community Cloud

1. Push this project to GitHub.
2. In Streamlit Community Cloud, create a new app from the repository.
3. Set the entrypoint to `app.py`.
4. Add this secret in the app settings:

```toml
FUGLE_API_KEY = "your_fugle_api_key"
```

## Next ideas

- watchlist management
- intraday chart and volume chart
- alert rules for unusual prints or spread changes
- market filters for TWSE, TPEx, ETF

## References

- [TWSE real-time market data](https://www.twse.com.tw/zh/products/information/real-time.html)
- [TPEx real-time market data](https://www.tpex.org.tw/zh-tw/service/data/product/real-time.html)
- [Fugle market data docs](https://developer.fugle.tw/docs/data/intro/)
- [Streamlit Community Cloud docs](https://docs.streamlit.io/deploy/streamlit-community-cloud)
