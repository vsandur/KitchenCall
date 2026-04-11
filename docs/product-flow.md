# KitchenCall — Product flow (MVP PRD)

## 1. Overview

KitchenCall is a conversational AI system that answers restaurant phone calls, takes orders like a real staff member, and submits structured orders to the kitchen.

**Core principle:** **natural on the phone, strict underneath.**

The POC may use **local or browser sessions** first; **full inbound telephony** (e.g. Twilio/SIP) is a later phase. Objectives like “never miss a call” apply to the **full product**; the POC proves conversation, cart reliability, and dashboard handoff.

---

## 2. Objectives

### Primary goals

- Never miss an incoming call *(full product; depends on phone integration)*
- Capture complete and accurate orders
- Reduce staff interruption during rush hours
- Deliver a human-like ordering experience

### Success criteria

- Orders completed without human intervention *(where transfer is not requested)*
- No loss of cart state during conversation
- Smooth handling of interruptions and corrections
- Accurate final order confirmation (spoken summary matches structured cart)

---

## 3. Personas

### Restaurant owner

- Wants more captured revenue
- Needs reliability and simplicity
- Avoids operational complexity

### Staff

- Wants fewer phone interruptions
- Needs clean, accurate orders
- Avoids confusion during peak hours

### Caller

- Wants quick response
- Expects natural conversation
- Needs easy corrections and clarity

---

## 4. Experience principles

- Speak like real restaurant staff; short, natural phrasing
- Avoid robotic or corporate tone
- Maintain in-call memory at all times (cart is source of truth for what was ordered)
- Handle interruptions gracefully; never reset the order unintentionally
- Do not mention AI unless policy or regulation requires it

---

## 5. Functional flow

### 5.1 Incoming session

- System answers immediately (within constraints of the active channel)
- Uses a restaurant-specific greeting (config)

**Example:**

> “Hi, thanks for calling Mario’s Pizza, what can I get started for you?”

---

### 5.2 Intent understanding

Supported intents (priority order):

1. Place new order  
2. Menu / hours / location questions (limited FAQ in MVP)  
3. Pickup / delivery / timing (simple rules)  
4. Transfer to staff  
5. Repeat previous order **(Phase 2)**

---

### 5.3 Conversational order taking

Capture when applicable:

- Item name  
- Quantity  
- Size  
- Modifiers  
- Combo / side selections  
- Required clarifications driven by the **menu schema** (e.g. missing size)

**Menu constraint:** The assistant only commits line items and modifiers that **validate against the restaurant menu JSON** (or explicit “unavailable” handling). No free-invented SKUs.

**Example:**

> “Two cheeseburgers”  
> “Got it — regular or deluxe?”

---

### 5.4 In-call memory

Maintain a **structured cart** throughout the session.

**Cart includes:**

- Items (with stable line ids for targeting)  
- Modifiers and quantities  
- Order type  
- Customer details  
- Missing information  
- Session status  

All assistant responses should reflect the **current cart snapshot** so nothing is forgotten in speech or in data.

---

### 5.5 Corrections and changes

Support natural corrections.

**Examples:**

- “Make that a medium”  
- “No onions on one”  
- “Change the burger to a chicken sandwich”  

Mapped internally to structured actions: `add_item`, `modify_item`, `remove_item` (and related intents). The cart updates **without** dropping unrelated lines.

**Ambiguity:** If the caller’s reference is unclear (“not that one,” “the first one” with multiple candidates), the system **asks one clarifying question** or resolves by `item_id` — it does **not** guess high-impact changes.

---

### 5.6 Customer information capture

Collect when required:

- Name  
- Phone number  
- Address  
- Delivery notes  

Track missing fields in:

```text
metadata.missing_info
```

---

### 5.7 Final confirmation

Provide **one** clear summary that matches the cart exactly.

**Example:**

> “Alright, I’ve got one medium pepperoni pizza, garlic knots, and a Coke for pickup in 20 minutes. That right?”

**Confirmation gate:** The order is **not** persisted as **completed** until the customer gives **explicit affirmation** (e.g. yes / that’s right / correct). Readback alone does not finalize.

---

### 5.8 Order submission

After confirmation:

- Persist the structured order  
- Mark the session as complete  
- Show on dashboard  
- Archive or clear the active cart for that session  

---

### 5.9 Logging and memory

**Phase 1**

- Store transcript  
- Store structured order  
- Store session outcome (SQLite)

**Phase 2**

- Identify returning customers  
- Store order history  
- Enable reorder suggestions  

**Example:**

> “Want the same order as last time?”

---

### 5.10 Transfer to staff (MVP / POC)

For early builds, **transfer** may be a **stub**: e.g. polite message to the caller, session flagged for staff, and/or logged — not necessarily a live PBX handoff. Full phone transfer is **Phase 3+** alongside telephony.

---

## 6. Dashboard (MVP)

### Required views

- Current session  
- Active cart (live JSON)  
- Completed orders  
- Recent transcripts  
- Customer history **(Phase 2)**

---

## 7. Data model

### Cart schema (simplified)

```json
{
  "order_id": "temp_123",
  "order_type": "pickup",
  "items": [],
  "customer": {
    "name": null,
    "phone": null,
    "address": null
  },
  "metadata": {
    "missing_info": [],
    "status": "building"
  }
}
```

Line items in implementation carry stable ids (e.g. `item_1`) for corrections; extend this shape in code/schemas as needed.

---

## 8. Non-goals (MVP scope exclusions)

- Delivery dispatch systems  
- Deep POS integrations  
- Phone payments  
- Loyalty programs  
- Multilingual support  
- Franchise-level routing  

---

## 9. MVP summary

KitchenCall answers restaurant calls (or session-based demos in POC), takes orders conversationally, maintains full in-call memory, handles corrections and ambiguity safely, and submits accurate structured orders for staff — with a strict cart underneath and a clear confirmation gate before finalize.
