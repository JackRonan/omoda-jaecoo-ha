# OMODA / Jaecoo API sandbox

Standalone CLI to hit the OMODA/Jaecoo API directly, **outside Home Assistant**, for
debugging. It imports the integration's real auth/signing code from
`../custom_components/omoda_jaecoo/core/` — no duplication, no HA runtime. Every call
prints the **exact raw JSON** the API returned.

Nothing here modifies the integration, and **nothing is written under the repo**: the
minted token and your config live in `~/.omoda_jaecoo_sandbox/` (override with the
`OMODA_SANDBOX_HOME` env var). The repo only holds code + this README.

## Setup

```bash
cd sandbox
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python omoda_sandbox.py
```

You only need **email + PIN** — same as the integration. The **VIN is auto-discovered**
from `queryList` after login; you never type it. Set credentials via the menu
(`Edit config`), which saves to `~/.omoda_jaecoo_sandbox/omoda_sandbox.env`. (An
`omoda_sandbox.env.example` is included for reference only — copy it there if you'd
rather pre-fill by hand.)

## Typical flow

1. **Send OTP to email** — solves the captcha and triggers the email code.
2. **Confirm OTP → mint & save token** — mints `~/.omoda_jaecoo_sandbox/token.json`
   (isolated from the integration's own token) and auto-discovers the VIN, exactly like
   `config_flow._discover`. If the default code format fails, use **brute-force format**.
3. **Read endpoints** — dump raw telemetry: `queryList`, realtime, location, travel, theft.
4. **Commands** — actuate the car (asks for confirmation; needs `OMODA_PIN` to mint a taskId).
5. **Raw request** — fire any path/body at either the TSP-signed or BFF-bearer layer.

## API layers (why two signers)

| Layer | Auth | Signing | Used for |
|-------|------|---------|----------|
| BFF `.../api` | `Bearer <access_token>` | `omoda_auth.headers_post` (SHA256 sig) | login, `queryList`, `checkPassword` |
| TSP `tspconsole-eu` | `userToken` from `_bff_login` | `tsp_sign.sign_body` (base64(sha256).upper) | realtime, location, commands |

## Notes

- `token.json` here is written **unredacted** (raw observability). Keep it out of git.
- Commands **actuate the real vehicle**; the menu confirms before sending.
- Region is EU by default; change hosts/tenant/appId in config for other regions.
