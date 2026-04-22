# Test KitchenCall with a real phone call (Twilio)

This runbook assumes you use **Twilio** for PSTN and the API’s **Media Streams** path (`KITCHENCALL_TWILIO_BRIDGE_MODE=stream`).

## How it works (production mental model)

1. **Who calls whom** — The **customer** calls the **restaurant** from their own phone (cell, landline, etc.). The number they dial is whatever the business publishes. In this setup that is typically a **Twilio number** you assign to the restaurant, or an existing shop line **forwarded** into Twilio so callers still reach “the restaurant.” You do not place the call *from* Twilio; Twilio is the **carrier bridge** between the PSTN caller and your API.

2. **What Twilio does** — On ring, Twilio **POSTs** to KitchenCall (`/telephony/twilio/inbound`). The API creates a **session** (the same session concept as the web demo), returns **TwiML** (greeting + **Media Stream**), then streams audio **both ways** over **WSS** so the server can run **STT → order logic → TTS**.

3. **Order logic** — Utterances go through the same **`process-turn`** path as the dashboard: cart and transcript live in the API database (`SQLite` in the POC).

4. **Where staff see it** — The **dashboard** (`apps/web`) polls **`GET /sessions`** and **`GET /orders`**. During the call, that session appears with a **live cart and transcript**; after the caller confirms (e.g. spoken **yes**), the order is **finalized** and shows up under **completed orders**. Today there is a **single operator dashboard**, not a separate “chef-only” product; a kitchen tablet can use the same UI or a future KDS can read the same API.

**One line:** customer dials the restaurant number → Twilio → KitchenCall takes the order → staff see the session and completed order in the web dashboard.

## Which number do I call?

**Call the Twilio phone number you own** — the one listed in the Twilio Console under **Phone Numbers → Manage → Active numbers** (for example `+1 555 123 4567`). KitchenCall does **not** ship a shared public test number; your webhook and stream URL must point at **your** running API.

- **Trial account:** Twilio only connects calls **to** numbers you have [verified as caller IDs](https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account#verify-your-personal-phone-number). You still **dial your Twilio number** from that verified phone.
- **Production account:** You can call your Twilio number from any phone (subject to your Twilio and carrier rules).

## Prerequisites on the API host

1. **Public HTTPS + WSS** — Twilio hits your webhook over **HTTPS** and opens Media Streams over **WSS**. For local dev, use something like [ngrok](https://ngrok.com/) (or similar) so both resolve to the same API:
   - `https://<public>/telephony/twilio/inbound`
   - `wss://<public>/telephony/twilio/media`
2. **`ffmpeg` on PATH** — required for outbound mu-law audio so the caller can hear assistant replies (see [twilio-media-bridge.md](./twilio-media-bridge.md)).
3. **Telephony Python deps** — from `apps/api`:

   ```bash
   pip install -r requirements-telephony.txt
   ```

4. **STT** — set `KITCHENCALL_TWILIO_STREAM_STT_BACKEND=faster_whisper` (or `http` with your transcribe endpoint).

### Twilio says “We’re sorry, an application error has occurred”

That is Twilio’s generic message when the **voice webhook** fails (timeout, connection error, or non-2xx). Typical causes:

1. **Stale tunnel URL** — ngrok / Cloudflare Quick Tunnels change hostname when you restart them. Update **both** the Twilio number’s webhook and `KITCHENCALL_TWILIO_MEDIA_STREAM_URL` to the **same** new `https://…` / `wss://…` host, then restart uvicorn.
2. **API not running** or firewall blocking Twilio.
3. **Quick check** — open `https://<your-public-host>/telephony/twilio/debug-status` in a browser; if it does not load, Twilio cannot reach your webhook either.

## “Creating an API” on the Twilio website — what that means

**KitchenCall is your API** (FastAPI on your host). Twilio does **not** host that logic.

In the [Twilio Console](https://console.twilio.com/) you only configure **where Twilio sends HTTP requests** when a call hits your number. You are **not** required to use Twilio’s REST “API” or create a special developer object unless you want extras (below).

| Twilio Console thing | Needed for KitchenCall? |
|----------------------|-------------------------|
| **Account** (sign up / log in) | Yes |
| **Phone number** with Voice | Yes — **Phone Numbers → Manage → Buy a number** (trial includes one in supported regions) |
| **Voice webhook on that number** | Yes — tells Twilio which **URL** to `POST` when someone calls |
| **TwiML App** (`Voice → TwiML → TwiML Apps`) | **No** for the simple setup — optional (e.g. if you use `<Dial><Application>` later) |
| **API Keys / Account SID + Auth Token** | **Not required** for this POC’s inbound webhook + Media Streams — KitchenCall does not call Twilio’s REST API in that path |
| **Studio / Functions / Serverless** | **No** unless you build a custom flow that then forwards to KitchenCall |

**Simplest path:** one number → **Voice & Fax** → **A call comes in** → **Webhook**, **HTTP POST** → your public KitchenCall URL (next section).

## Twilio Console wiring

1. **Phone Numbers → Manage → Active numbers** → click your number.
2. Under **Voice & Fax** (or **Configure**), find **A call comes in**.
3. Set **Webhook**, method **HTTP POST**, URL:

   `https://<your-public-host>/telephony/twilio/inbound`

4. (Optional) **Call status changes** — Webhook **HTTP POST**:

   `https://<your-public-host>/telephony/twilio/status`

### Optional: `<Dial><Application>` for testing (Twilio docs pattern)

You **do not** need this for KitchenCall: pointing the number’s **Voice webhook** straight at `/telephony/twilio/inbound` is enough.

If you want to **practice the same idea as** [Twilio’s `<Dial><Application>` example](https://www.twilio.com/docs/voice/twiml/dial/application/usage) (e.g. “entry” leg dials into a **TwiML App** that runs KitchenCall):

1. In **Twilio Console → Voice → TwiML → TwiML Apps**, create an app whose **Voice URL** is  
   `https://<your-public-host>/telephony/twilio/inbound` (same as above). Note the app’s **Application SID** (`AP…`).
2. On a **second** number (or a [TwiML Bin](https://www.twilio.com/docs/serverless/twiml-bins) / Studio flow used as the first webhook), set the incoming handler to return TwiML like:

   ```xml
   <Response>
     <Dial>
       <Application>
         <ApplicationSid>APxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</ApplicationSid>
       </Application>
     </Dial>
   </Response>
   ```

3. **Same Twilio account:** Twilio documents that transfers within one account need no extra checkbox. **Two different accounts:** the **receiving** TwiML App must allow “Application Dialing from other Twilio Accounts,” and you should treat the App SID as sensitive (see Twilio’s security note on that page).

When the dial completes, Twilio requests your KitchenCall **Voice URL** for the **child** call; you get a normal inbound `POST` with `CallSid`, `From`, `To`, etc., and Media Streams behave the same as a direct number→webhook setup.

## API environment (minimal for a spoken ordering test)

Set these (see `apps/api/.env.example` for all names):

| Variable | Example / note |
|----------|----------------|
| `KITCHENCALL_TWILIO_BRIDGE_MODE` | `stream` |
| `KITCHENCALL_TWILIO_MEDIA_STREAM_URL` | `wss://<your-public-host>/telephony/twilio/media` |
| `KITCHENCALL_TWILIO_STREAM_TRACK` | Ignored for `<Connect><Stream>` — Twilio allows only `inbound_track`; assistant audio to the caller is sent as WebSocket `media` messages (still needs **`ffmpeg`** for TTS). |
| `KITCHENCALL_TWILIO_STREAM_STT_BACKEND` | `faster_whisper` or `http` |
| `KITCHENCALL_TWILIO_STREAM_TTS_BACKEND` | `auto` (default: TTS on when STT is on) or `on` / `off` |
| `KITCHENCALL_TWILIO_VOICE_GREETING` | Optional; empty uses built-in ordering intro before the stream |

Start the API (e.g. `uvicorn` on the port your tunnel forwards).

### PersonaPlex (optional natural voice)

If `KITCHENCALL_PERSONAPLEX_ENABLED=true`, run PersonaPlex-MLX locally (see `apps/personaplex/`; default WebSocket `ws://localhost:8998/api/chat`). **Restart the PersonaPlex process after you pull changes that touch `apps/personaplex/`** (for example `personaplex_mlx/local_web.py`). Restarting only the KitchenCall API does not reload that server.

**Sanity check (no phone):** From the repo root, run **`./poc/scripts/verify_phone_stack.sh http://127.0.0.1:8000`** (or your public base URL). The script hits **`/health`**, **`/telephony/twilio/debug-status`**, and **`/telephony/twilio/personaplex-probe`**. For **`personaplex-probe`**, you want **`ok: true`** and **`handshake_first_byte: 0`**. If you see **HTTP 400** / handshake errors, fix **PersonaPlex** (e.g. missing voice `NATF2.pt` under the voices directory) and **restart the PersonaPlex process** so **`apps/personaplex/personaplex_mlx/local_web.py`** is current. If the probe says the socket closed before handshake, another session may be holding the model lock — stop other PersonaPlex clients or set **`PERSONAPLEX_LOCK_ACQUIRE_TIMEOUT`** (seconds) on the PersonaPlex process. If prompts are huge, trim the menu or adjust **`KITCHENCALL_PERSONAPLEX_PROMPT_MAX_CHARS`** (very long URLs can break the WebSocket upgrade).

## Checklist — Render (host) vs Twilio (phone)

Use one **public hostname** for both sides (e.g. `kitchencall-api-xxxx.onrender.com`). Replace `YOUR-HOST` below with that host **without** `https://` or `wss://`.

### A. Render (KitchenCall API)

1. **Deploy** the repo; confirm **`https://YOUR-HOST/health`** returns `{"status":"ok"}`.
2. **Root Directory:** leave **empty** if you use the repo-root [`Dockerfile`](../Dockerfile) (see [api-hosting.md](./api-hosting.md)).
3. **Environment** (Dashboard → your Web Service → **Environment**), add at least:

   | Key | Value |
   |-----|--------|
   | `KITCHENCALL_TWILIO_BRIDGE_MODE` | `stream` |
   | `KITCHENCALL_TWILIO_MEDIA_STREAM_URL` | `wss://YOUR-HOST/telephony/twilio/media` |

   Optional: `KITCHENCALL_CORS_ORIGINS` = your dashboard URL(s), comma-separated.  
   **Speech-to-cart:** the repo **Dockerfile** installs **faster-whisper**, **ffmpeg**, and **espeak-ng** and sets `KITCHENCALL_TWILIO_STREAM_STT_BACKEND=faster_whisper` by default. Override with `off` if you only want the stream without ordering, or `http` + `KITCHENCALL_TWILIO_STT_HTTP_URL` for an external STT service. On **small Render instances**, set `KITCHENCALL_TWILIO_WHISPER_MODEL=tiny` if the first utterance times out or the service restarts (model download + RAM).  
   **Tone before listening:** TwiML plays `https://YOUR-HOST/telephony/twilio/assets/phone-beep.wav` (served by the API) right before `<Connect><Stream>`, so the caller hears a real beep after the greeting.

4. **Save** env vars and **trigger a deploy** (or wait for auto-deploy).
5. **Persistent disk (recommended):** **Settings → Disks** → mount path **`/app/data`** so SQLite survives restarts.

### B. Twilio Console

1. **Phone number** with Voice (trial numbers work for testing).
2. **Phone Numbers → your number → Voice & Fax:**
   - **A call comes in:** **Webhook**, **HTTP POST**  
     `https://YOUR-HOST/telephony/twilio/inbound`
   - **Call status changes (optional):** **HTTP POST**  
     `https://YOUR-HOST/telephony/twilio/status`
3. **Trial account:** verify the **caller ID** you will call from ([Twilio trial rules](https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account)).

### C. Same host everywhere

| Where | URL |
|-------|-----|
| Twilio Voice webhook | `https://YOUR-HOST/telephony/twilio/inbound` |
| Render env `KITCHENCALL_TWILIO_MEDIA_STREAM_URL` | `wss://YOUR-HOST/telephony/twilio/media` |

### D. First call

Dial your Twilio number → you should hear the **greeting** (menu vs. order options) → with **STT on**, say **menu** to hear items or place an order; confirm in **`GET /sessions`** or the dashboard.

### E. Dashboard — phone call log

The web dashboard polls **`GET /telephony/twilio/calls`**, which returns recent calls with a **timeline** (every transcript line, including **`call`** events and Twilio status updates) with **ISO timestamps** shown in your local time. Sessions that came from a phone call show a **Phone** badge in the session list.

## Local sanity checks (no phone)

```bash
python3 poc/scripts/verify_twilio_mapping.py --base http://127.0.0.1:8000
python3 poc/scripts/verify_twilio_tts_local.py
```

The second script needs `ffmpeg` and a local TTS backend (`say` on macOS, or `espeak-ng` / `pyttsx3` on Linux).

## Call flow to exercise

1. Dial **your Twilio number** from your phone.
2. You should hear the **greeting** (TwiML `<Say>`), then the stream connects.
3. Speak an order (e.g. menu items, then **“that’s all”** when ready).
4. When the assistant asks you to confirm, say **yes** — the session **finalizes on the server** (same effect as `POST /sessions/{id}/finalize` with `affirmed: true`) and you should hear a short thank-you line if TTS is enabled.
5. Confirm in the **dashboard** or `GET /sessions/{id}` / `GET /orders` that the cart reached `completed` and an order row exists.

## Troubleshooting: call drops right after the greeting / when you start talking

1. **Twilio Debugger** (Console → **Monitor → Logs → Debugger**) — note any **319xx** / stream errors.
2. **Render → Logs** — look for `telephony STT failed`, `ImportError`, `faster-whisper`, or WebSocket tracebacks.
3. **STT on Render without telephony deps** — the default API Docker image only installs `requirements.txt` (no **`faster-whisper`** / **`numpy`**). If `KITCHENCALL_TWILIO_STREAM_STT_BACKEND=faster_whisper`, either install [requirements-telephony.txt](../apps/api/requirements-telephony.txt) in the image or use **`http`** STT, or set **`KITCHENCALL_TWILIO_STREAM_STT_BACKEND=off`** until the image is extended. The API now catches STT failures so the **call should stay up** even if STT misconfigured (you just won’t get speech-to-cart until STT works).
4. **Cold start (free tier)** — first call after sleep can be flaky; retry or use a paid instance.

## See also

- [twilio-media-bridge.md](./twilio-media-bridge.md) — STT, utterance segmentation, outbound audio details
