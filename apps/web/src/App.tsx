import { useCallback, useEffect, useRef, useState } from "react";
import { Room, RoomEvent } from "livekit-client";

const API = "/api";

type SessionRow = { id: string; phase: string; transfer_requested?: boolean; updated_at?: string };
type TranscriptLine = {
  id: number;
  role: string;
  text: string;
  is_partial: boolean;
  created_at: string;
};
type SessionDetail = {
  id: string;
  phase: string;
  transfer_requested: boolean;
  cart: Record<string, unknown>;
  transcript: TranscriptLine[];
  applied_intents?: string[];
  errors?: string[];
  affirmation_hint?: string | null;
  assistant_response?: string;
};

type OrderRow = { id: number; session_id: string; created_at: string; cart: Record<string, unknown> };
type AgentStatus = {
  available: boolean;
  reason: string;
  heartbeat_age_seconds: number | null;
  stt_backend?: string | null;
  tts_backend?: string | null;
};

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onstart: (() => void) | null;
  onerror: ((e: Event) => void) | null;
  onend: (() => void) | null;
  onresult: ((e: SpeechRecognitionEvent) => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

type SpeechRecognitionEvent = Event & {
  resultIndex: number;
  results: {
    [index: number]: { isFinal: boolean; 0: { transcript: string } };
    length: number;
  };
};

type CartLine = { name: string; subtitle: string; qty: number };
type Toast = { kind: "error" | "ok"; message: string } | null;

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const PHASE_LABELS: Record<string, string> = {
  greeting: "Welcome — say what you’d like to order",
  ordering: "Taking your order",
  confirming: "Review — say yes to place the order",
  completed: "Order complete",
  cancelled: "Cancelled",
  transfer: "Handoff to staff",
};

function humanPhase(phase: string): string {
  return PHASE_LABELS[phase] ?? phase.replace(/_/g, " ");
}

function parseCartLines(cart: Record<string, unknown>): CartLine[] {
  const raw = cart.items;
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const o = item as Record<string, unknown>;
    const name = typeof o.name === "string" ? o.name : String(o.menu_item_id ?? "Item");
    const qty = typeof o.qty === "number" && o.qty >= 1 ? o.qty : 1;
    const parts: string[] = [];
    if (typeof o.size === "string" && o.size) parts.push(o.size);
    const mods = o.modifiers;
    if (Array.isArray(mods) && mods.length) parts.push(mods.join(", "));
    if (typeof o.special_instructions === "string" && o.special_instructions.trim())
      parts.push(`Note: ${o.special_instructions.trim()}`);
    return { name, subtitle: parts.join(" · "), qty };
  });
}

function cartCustomerSummary(cart: Record<string, unknown>): string[] {
  const c = cart.customer as Record<string, unknown> | undefined;
  if (!c || typeof c !== "object") return [];
  const lines: string[] = [];
  if (typeof c.name === "string" && c.name.trim()) lines.push(`Name: ${c.name.trim()}`);
  if (typeof c.phone === "string" && c.phone.trim()) lines.push(`Phone: ${c.phone.trim()}`);
  if (typeof c.address === "string" && c.address.trim()) lines.push(`Address: ${c.address.trim()}`);
  return lines;
}

function orderTypeLabel(cart: Record<string, unknown>): string {
  const t = cart.order_type;
  if (t === "delivery") return "Delivery";
  if (t === "pickup") return "Pickup";
  return "";
}

function statusLabel(cart: Record<string, unknown>): string {
  const meta = cart.metadata as Record<string, unknown> | undefined;
  const s = meta?.status;
  return typeof s === "string" ? s : "";
}

function AgentStatusPill({ status }: { status: AgentStatus | null }) {
  if (!status) {
    return (
      <span className="status-pill status-pill--unknown" title="Could not reach the API">
        Agent: checking…
      </span>
    );
  }
  if (status.available) {
    const backends = [status.stt_backend, status.tts_backend].filter(Boolean).join(" · ");
    return (
      <span className="status-pill status-pill--ok" title={backends || "Worker heartbeat OK"}>
        Voice agent online
        {backends ? ` · ${backends}` : ""}
      </span>
    );
  }
  return (
    <span className="status-pill status-pill--bad" title={status.reason}>
      Voice agent offline
    </span>
  );
}

function CartSummary({ cart }: { cart: Record<string, unknown> }) {
  const lines = parseCartLines(cart);
  const customer = cartCustomerSummary(cart);
  const ot = orderTypeLabel(cart);
  const st = statusLabel(cart);

  return (
    <div className="cart-card">
      {lines.length === 0 ? (
        <p className="cart-empty">Your cart is empty. Try saying or typing an item (e.g. “large pepperoni for pickup”).</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {lines.map((line, i) => (
            <li key={i} className="cart-line">
              <div>
                <div className="cart-line-name">
                  {line.name}
                  {line.qty > 1 ? <span style={{ color: "var(--text-muted)", fontWeight: 500 }}> ×{line.qty}</span> : null}
                </div>
                {line.subtitle ? <div className="cart-line-detail">{line.subtitle}</div> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      {(ot || customer.length || st) && (
        <div className="cart-meta">
          {ot && <div>{ot}</div>}
          {customer.map((x, i) => (
            <div key={i}>{x}</div>
          ))}
          {st && (
            <div>
              Status: <strong style={{ color: "var(--text)" }}>{st}</strong>
            </div>
          )}
        </div>
      )}
      <details className="raw-json">
        <summary>Technical: full cart JSON</summary>
        <pre>{JSON.stringify(cart, null, 2)}</pre>
      </details>
    </div>
  );
}

function TranscriptThread({ lines }: { lines: TranscriptLine[] }) {
  if (!lines.length) {
    return <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.875rem" }}>No messages yet.</p>;
  }
  return (
    <div className="transcript" role="log" aria-live="polite" aria-relevant="additions">
      {lines.map((t) => {
        const role = t.role.toLowerCase();
        const cls =
          role === "user" || role === "customer"
            ? "msg msg--user"
            : role === "assistant" || role === "staff" || role === "system"
              ? "msg msg--assistant"
              : "msg msg--system";
        return (
          <div key={t.id} className={t.is_partial ? `${cls} msg-partial` : cls}>
            <span className="sr-only">{t.role}: </span>
            {t.text}
            {t.is_partial ? " …" : ""}
          </div>
        );
      })}
    </div>
  );
}

function OrderSummaryCard({ order }: { order: OrderRow }) {
  const lines = parseCartLines(order.cart);
  const date = new Date(order.created_at);
  const when = Number.isNaN(date.getTime()) ? order.created_at : date.toLocaleString();

  return (
    <li className="order-card">
      <div className="order-card-head">
        <strong>Order #{order.id}</strong>
        <span>{when}</span>
      </div>
      {lines.length === 0 ? (
        <pre style={{ fontSize: "0.75rem", margin: 0, overflow: "auto" }}>{JSON.stringify(order.cart, null, 2)}</pre>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {lines.map((line, i) => (
            <li key={i} className="cart-line">
              <div>
                <div className="cart-line-name">
                  {line.name}
                  {line.qty > 1 ? ` ×${line.qty}` : ""}
                </div>
                {line.subtitle ? <div className="cart-line-detail">{line.subtitle}</div> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      <details className="raw-json" style={{ marginTop: "0.5rem" }}>
        <summary>JSON</summary>
        <pre>{JSON.stringify(order.cart, null, 2)}</pre>
      </details>
    </li>
  );
}

export default function App() {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [input, setInput] = useState("");
  const [lastProcess, setLastProcess] = useState<SessionDetail | null>(null);
  const [micSupported, setMicSupported] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [partialText, setPartialText] = useState("");
  const [voiceReplyEnabled, setVoiceReplyEnabled] = useState(true);
  const [lkRoom, setLkRoom] = useState<Room | null>(null);
  const [lkBusy, setLkBusy] = useState(false);
  const [lkError, setLkError] = useState<string | null>(null);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [toast, setToast] = useState<Toast>(null);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const partialTimerRef = useRef<number | null>(null);
  const lkRoomRef = useRef<Room | null>(null);
  const toastTimerRef = useRef<number | null>(null);

  const speak = useCallback((text?: string) => {
    if (!voiceReplyEnabled || !text) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.03;
    u.pitch = 1.0;
    window.speechSynthesis.speak(u);
  }, [voiceReplyEnabled]);

  const showToast = useCallback((t: Toast) => {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    setToast(t);
    if (t) {
      toastTimerRef.current = window.setTimeout(() => setToast(null), 4500);
    }
  }, []);

  const refreshSessions = useCallback(() => {
    fetch(`${API}/sessions`)
      .then((r) => r.json())
      .then(setSessions)
      .catch(console.error);
  }, []);

  const refreshOrders = useCallback(() => {
    fetch(`${API}/orders`)
      .then((r) => r.json())
      .then(setOrders)
      .catch(console.error);
  }, []);

  useEffect(() => {
    setMicSupported(Boolean(getSpeechRecognitionCtor()));
    refreshSessions();
    refreshOrders();
  }, [refreshSessions, refreshOrders]);

  useEffect(() => {
    const tick = () => {
      fetch(`${API}/agent/status`)
        .then((r) => r.json())
        .then((x: AgentStatus) => setAgentStatus(x))
        .catch(() => setAgentStatus(null));
    };
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    lkRoomRef.current = lkRoom;
  }, [lkRoom]);

  useEffect(
    () => () => {
      lkRoomRef.current?.disconnect();
      if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    if (!sel) {
      setDetail(null);
      return;
    }
    const tick = () => {
      fetch(`${API}/sessions/${sel}`)
        .then((r) => r.json())
        .then(setDetail)
        .catch(console.error);
    };
    tick();
    const id = setInterval(tick, 1200);
    return () => clearInterval(id);
  }, [sel]);

  const createSession = () => {
    fetch(`${API}/sessions`, { method: "POST" })
      .then((r) => r.json())
      .then((x: SessionDetail) => {
        setSel(x.id);
        setDetail(x);
        refreshSessions();
        showToast({ kind: "ok", message: "New order started. Say or type what you’d like." });
      })
      .catch(console.error);
  };

  const postPartial = useCallback((text: string) => {
    if (!sel || !text.trim()) return;
    fetch(`${API}/sessions/${sel}/transcript`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: "user", text: text.trim(), is_partial: true }),
    }).catch(() => undefined);
  }, [sel]);

  const sendTurn = useCallback(
    (turnText?: string) => {
      const text = (turnText ?? input).trim();
      if (!sel || !text) return;
      fetch(`${API}/sessions/${sel}/process-turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      })
        .then((r) => r.json())
        .then((x: SessionDetail) => {
          setLastProcess(x);
          setDetail(x);
          setInput("");
          setPartialText("");
          refreshSessions();
          speak(x.assistant_response);
        })
        .catch(console.error);
    },
    [input, refreshSessions, sel, speak],
  );

  const stopMic = useCallback(() => {
    recognitionRef.current?.stop();
    setIsListening(false);
  }, []);

  const connectLiveKit = useCallback(async () => {
    if (!sel) return;
    setLkError(null);
    setLkBusy(true);
    try {
      const res = await fetch(`${API}/livekit/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sel,
          participant_identity: `web-${sel.slice(0, 8)}`,
        }),
      });
      const payload = (await res.json().catch(() => ({}))) as {
        detail?: unknown;
        url?: string;
        token?: string;
      };
      if (!res.ok) {
        const d = payload.detail;
        const msg =
          typeof d === "string" ? d : Array.isArray(d) ? JSON.stringify(d) : res.statusText;
        throw new Error(msg || `HTTP ${res.status}`);
      }
      const { url, token } = payload;
      if (!url || !token) throw new Error("Invalid token response from API");
      window.speechSynthesis.cancel();
      const room = new Room({ adaptiveStream: true, dynacast: true });
      room.on(RoomEvent.Disconnected, () => {
        setLkRoom(null);
      });
      await room.connect(url, token);
      await room.localParticipant.setMicrophoneEnabled(true);
      setLkRoom(room);
      showToast({ kind: "ok", message: "Connected to voice room. Speak naturally." });
    } catch (e) {
      setLkError((e as Error).message || "LiveKit connect failed");
      setLkRoom(null);
    } finally {
      setLkBusy(false);
    }
  }, [sel, showToast]);

  const disconnectLiveKit = useCallback(() => {
    lkRoomRef.current?.disconnect();
    setLkRoom(null);
    setLkError(null);
  }, []);

  const startMic = useCallback(() => {
    if (!sel) return;
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;

    window.speechSynthesis.cancel();

    const rec = new Ctor();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onstart = () => setIsListening(true);
    rec.onerror = () => setIsListening(false);
    rec.onend = () => setIsListening(false);
    rec.onresult = (evt: SpeechRecognitionEvent) => {
      let finalText = "";
      let interim = "";
      for (let i = evt.resultIndex; i < evt.results.length; i += 1) {
        const seg = evt.results[i][0]?.transcript ?? "";
        if (evt.results[i].isFinal) finalText += `${seg} `;
        else interim += `${seg} `;
      }
      const trimmedInterim = interim.trim();
      setPartialText(trimmedInterim);
      if (trimmedInterim) {
        if (partialTimerRef.current) window.clearTimeout(partialTimerRef.current);
        partialTimerRef.current = window.setTimeout(() => postPartial(trimmedInterim), 250);
      }
      const ft = finalText.trim();
      if (ft) sendTurn(ft);
    };

    recognitionRef.current = rec;
    rec.start();
  }, [postPartial, sel, sendTurn]);

  const finalize = () => {
    if (!sel) return;
    fetch(`${API}/sessions/${sel}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ affirmed: true }),
    })
      .then((r) => {
        if (!r.ok) return r.json().then((j) => Promise.reject(j));
        return r.json();
      })
      .then(() => {
        refreshOrders();
        refreshSessions();
        showToast({ kind: "ok", message: "Order placed. Thank you!" });
        if (sel) {
          fetch(`${API}/sessions/${sel}`)
            .then((r) => r.json())
            .then(setDetail);
        }
      })
      .catch((e) => {
        const msg =
          typeof e?.detail === "string"
            ? e.detail
            : Array.isArray(e?.detail)
              ? e.detail.map((x: { msg?: string }) => x.msg ?? JSON.stringify(x)).join("; ")
              : typeof e === "object"
                ? JSON.stringify(e)
                : String(e);
        showToast({ kind: "error", message: msg || "Could not finalize order." });
      });
  };

  const canFinalize = detail?.phase === "confirming" && !detail.transfer_requested;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-inner">
          <div className="brand">
            <h1 className="brand-title">KitchenCall</h1>
            <p className="brand-tagline">
              Order by voice or text. Your cart updates as you go — confirm when you’re ready.
            </p>
          </div>
          <AgentStatusPill status={agentStatus} />
        </div>
      </header>

      <main className="app-main">
        <div className="layout-grid">
          <aside className="panel">
            <div className="panel-header">
              <span>Your orders</span>
              <span className="badge">{sessions.length}</span>
            </div>
            <div className="panel-body">
              <div className="btn-row" style={{ marginBottom: "1rem" }}>
                <button type="button" className="btn-primary" onClick={createSession}>
                  Start new order
                </button>
              </div>
              <p className="section-title" style={{ marginBottom: "0.5rem" }}>
                Active sessions
              </p>
              {sessions.length === 0 ? (
                <p style={{ margin: 0, fontSize: "0.875rem", color: "var(--text-muted)" }}>
                  No sessions yet. Tap “Start new order” above.
                </p>
              ) : (
                <ul className="session-list">
                  {sessions.map((s) => (
                    <li key={s.id}>
                      <button
                        type="button"
                        className={`session-item${sel === s.id ? " session-item--active" : ""}`}
                        onClick={() => setSel(s.id)}
                      >
                        <span className="session-item-id">{s.id.slice(0, 8)}…</span>
                        <span className="session-item-meta">
                          {humanPhase(s.phase)}
                          {s.transfer_requested ? (
                            <>
                              {" "}
                              <span className="badge badge--warn">Transfer</span>
                            </>
                          ) : null}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="btn-row" style={{ marginTop: "1rem" }}>
                <button type="button" className="btn-ghost" onClick={refreshSessions}>
                  Refresh list
                </button>
              </div>
            </div>
          </aside>

          <article className="panel">
            <div className="panel-header">
              <span>{detail ? "Current order" : "Select or start an order"}</span>
            </div>
            <div className="panel-body">
              {!detail && (
                <div className="empty-workspace">
                  <h2>Nothing selected</h2>
                  <p>Choose a session on the left, or start a new order to try the demo.</p>
                  <button type="button" className="btn-primary" onClick={createSession}>
                    Start new order
                  </button>
                </div>
              )}

              {detail && (
                <>
                  <div className="phase-banner">
                    <span className="phase-label">{humanPhase(detail.phase)}</span>
                    {detail.transfer_requested && (
                      <span className="badge badge--warn">Staff transfer requested</span>
                    )}
                  </div>

                  <p className="section-title">How do you want to talk?</p>
                  <div className="voice-section">
                    <p className="voice-hint">
                      <strong>Browser mic</strong> uses your browser’s speech recognition (quick to try).{" "}
                      <strong>LiveKit</strong> uses the cloud voice agent when your API and worker are configured. Use
                      only one at a time so the assistant doesn’t hear double audio.
                    </p>
                    <div className="btn-row">
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={startMic}
                        disabled={!micSupported || isListening || !sel}
                      >
                        {isListening ? "Listening…" : "Use browser mic"}
                      </button>
                      <button type="button" className="btn-secondary" onClick={stopMic} disabled={!isListening}>
                        Stop browser mic
                      </button>
                      <button
                        type="button"
                        className={voiceReplyEnabled ? "btn-toggle-on" : "btn-secondary"}
                        onClick={() => setVoiceReplyEnabled((v) => !v)}
                      >
                        {voiceReplyEnabled ? "Read replies aloud" : "Replies: text only"}
                      </button>
                    </div>
                    {!micSupported && (
                      <p className="inline-error" style={{ marginTop: "0.5rem", display: "block" }}>
                        This browser doesn’t support speech recognition. Use Chrome or type below.
                      </p>
                    )}
                    {partialText ? <p className="listening-banner">Hearing: {partialText}</p> : null}

                    <div className="btn-row" style={{ marginTop: "0.75rem" }}>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => void connectLiveKit()}
                        disabled={!sel || lkBusy || Boolean(lkRoom)}
                      >
                        {lkBusy ? "Connecting…" : lkRoom ? "LiveKit connected" : "Connect LiveKit voice"}
                      </button>
                      <button type="button" className="btn-ghost" onClick={disconnectLiveKit} disabled={!lkRoom}>
                        Disconnect LiveKit
                      </button>
                    </div>
                    {lkError && (
                      <p className="alert alert--error" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
                        {lkError}
                      </p>
                    )}
                    {lkRoom && (
                      <p style={{ margin: "0.75rem 0 0", fontSize: "0.8125rem", color: "var(--success)" }}>
                        Room audio is handled by the voice agent. Stop the browser mic if it’s still on.
                      </p>
                    )}
                  </div>

                  <p className="section-title">Cart</p>
                  <CartSummary cart={detail.cart} />

                  <p className="section-title">Conversation</p>
                  <TranscriptThread lines={detail.transcript ?? []} />

                  <div className="compose">
                    <label htmlFor="order-input" className="sr-only">
                      Type your message
                    </label>
                    <input
                      id="order-input"
                      type="text"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && sendTurn()}
                      placeholder="e.g. large pepperoni for pickup, then say that's all"
                      autoComplete="off"
                    />
                    <button type="button" className="btn-primary" onClick={() => sendTurn()}>
                      Send
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={finalize}
                      disabled={!canFinalize}
                      title={
                        canFinalize
                          ? "Confirm and save this order"
                          : "Available when the order is in the confirming step"
                      }
                    >
                      Place order
                    </button>
                  </div>
                  {!canFinalize && detail.phase !== "completed" && (
                    <p style={{ margin: "0.5rem 0 0", fontSize: "0.8125rem", color: "var(--text-muted)" }}>
                      “Place order” unlocks after you finish ordering and confirm with <strong>yes</strong> when asked.
                    </p>
                  )}

                  {lastProcess?.assistant_response && (
                    <div className="reply-card">
                      <strong>Assistant</strong>
                      {lastProcess.assistant_response}
                    </div>
                  )}
                  {lastProcess?.errors && lastProcess.errors.length > 0 && (
                    <div className="alert alert--error">{lastProcess.errors.join(", ")}</div>
                  )}
                  {lastProcess?.affirmation_hint && (
                    <div className="alert alert--hint">{lastProcess.affirmation_hint}</div>
                  )}
                </>
              )}
            </div>
          </article>
        </div>

        <section className="orders-section panel">
          <div className="panel-header">
            <span>Completed orders</span>
            <span className="badge">{orders.length}</span>
          </div>
          <div className="panel-body">
            <div className="btn-row" style={{ marginBottom: "1rem" }}>
              <button type="button" className="btn-ghost" onClick={refreshOrders}>
                Refresh
              </button>
            </div>
            {orders.length === 0 ? (
              <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9375rem" }}>
                No completed orders yet. Finish an order with “Place order” when prompted.
              </p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {orders.map((o) => (
                  <OrderSummaryCard key={o.id} order={o} />
                ))}
              </ul>
            )}
          </div>
        </section>
      </main>

      {toast && (
        <div className={`toast toast--${toast.kind === "error" ? "error" : "ok"}`} role="status">
          {toast.message}
        </div>
      )}
    </div>
  );
}
