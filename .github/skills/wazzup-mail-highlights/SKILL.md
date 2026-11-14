---
name: wazzup-mail-highlights
description: Scan the signed-in user's mailbox, pick the top highlights (what needs them, decisions, deadlines, worth-knowing updates), and email them a polished, modern HTML digest. Use when asked for "mail highlights", "inbox digest", "what's important in my mailbox", "wazzup my inbox", or to send an email summary of recent mail to themselves.
---

# Wazzup mail highlights

Deliver a short, high-signal digest of the user's mailbox as a slick, modern
HTML email sent **only to the user themself**. The skill folder (this file plus
`templates/`) works from Microsoft 365 Copilot Cowork and from GitHub Copilot
(CLI / VS Code) alike.

## Guardrails

- **Read-only on the mailbox.** Never reply to, forward, move, delete, flag,
  categorize, or mark messages as read. The only write action allowed is
  sending the digest.
- **Recipient is always the signed-in user.** Resolve the user's own primary
  SMTP address (for example `GET /me` → `mail`). Never add other recipients,
  CC, or BCC. If the user asks to send it elsewhere, confirm explicitly first.
- **Never copy secrets into the digest.** Skip or redact one-time codes, MFA
  prompts, passwords, reset links, and full payment or identity numbers.
- For messages labelled Confidential / Highly Confidential, summarize at a
  high level only and never quote the body.
- Do not invent facts, dates, or asks. Every highlight must trace back to a
  real message and link to it.

## Inputs (all optional)

| Input         | Default                                                                  |
| ------------- | ------------------------------------------------------------------------ |
| Time window   | Since the last Wazzup mail digest; otherwise last 24h (72h on Mondays)   |
| Highlights    | Up to 5 featured highlights, plus up to 6 quick hits                     |
| Folders       | Inbox (Focused + Other); read sent items only to detect answered threads |
| VIPs          | Manager, skip-level, direct reports, and people the user mailed recently |
| Language/tone | The user's language; crisp, friendly, no corporate filler                |
| Time zone     | The user's mailbox time zone (fall back to `Europe/Amsterdam`)           |

If the user gives explicit values ("last 3 days", "only top 3"), use them.

## Step 1 — Collect

Use whichever mail capability the host exposes, in this order of preference:

1. **Cowork:** the built-in Outlook mail tools (search, read, send).
2. **GitHub Copilot:** Work IQ / Microsoft 365 MCP tools, or Microsoft Graph:
   - `GET /me` and `GET /me/mailboxSettings` (name, address, time zone)
   - `GET /me/mailFolders/inbox/messages?$filter=receivedDateTime ge {start}&$orderby=receivedDateTime desc&$top=100&$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,importance,flag,isRead,hasAttachments,bodyPreview,conversationId,inferenceClassification,webLink`
   - `GET /me/manager` and `GET /me/directReports` to seed VIPs.

To find the start of the window, search sent items for the most recent message
whose subject starts with `Wazzup ·`. Fetch full bodies only for candidates
that survive Step 2, and stop paging after ~300 messages.

If no send-capable mail tool is available, stop before Step 5 and tell the user
which capability is missing instead of improvising another channel.

## Step 2 — Filter out noise

Drop messages that are:

- Previous Wazzup digests, or anything the user sent to themself.
- Newsletters, marketing, social notifications, and bulk mail (look for
  `List-Unsubscribe`, `noreply`/`no-reply` senders, or "Other" inference
  classification) — unless they come from a VIP or mention the user directly.
- Calendar auto-responses (accepted/declined/tentative) with no added text.
- Automated alerts that self-resolved later in the same window.

Collapse each conversation into one candidate, using the latest message for
status but all messages for context.

## Step 3 — Score and pick

Score each candidate 0–100 and keep the best. Weigh roughly:

| Signal                                                                  | Weight |
| ----------------------------------------------------------------------- | ------ |
| Explicit ask of the user (question, approval, review, "can you", @name) | +30    |
| Deadline or time-bound item within the next 7 days                      | +20    |
| Sender is a VIP                                                         | +20    |
| User is on **To** (not only CC), or the thread names them               | +10    |
| High importance, or flagged by the user                                 | +10    |
| Active thread (3+ replies in window) or a decision was made             | +10    |
| Unread                                                                  | +5     |
| User already replied after the latest message                           | −30    |
| Purely informational with no impact on the user                         | −15    |

Assign each pick exactly one category:

| Category    | Use when                                           |
| ----------- | -------------------------------------------------- |
| `NEEDS YOU` | The user must act, answer, approve, or attend      |
| `DEADLINE`  | A concrete due date or expiring item               |
| `DECISION`  | Something was decided or changed that affects them |
| `FYI`       | Worth knowing, no action needed                    |

Featured highlights are the top 3–5 by score, ordered `NEEDS YOU` →
`DEADLINE` → `DECISION` → `FYI`, then by score. The next up to 6 become quick
hits. If nothing clears ~40 points, send the "all quiet" variant instead of
padding the digest.

## Step 4 — Write

For every featured highlight, write:

- **Headline:** rewrite the subject into a plain-language headline (max ~70
  characters). No `RE:`/`FW:` prefixes and no ticket noise.
- **Summary:** 1–2 sentences on what happened and why it matters to the user.
- **Next step:** one imperative line ("Approve the budget in the thread by
  Thu 17:00"). For `FYI`, use "No action needed".
- **Meta:** sender display name, relative time ("2h ago", "Yesterday 16:40"),
  and the message `webLink` for the "Open" button.

For quick hits, write a single line: `Sender — what it is`, linked to the
message.

Also write:

- **TL;DR:** one sentence covering the overall picture ("Two approvals are
  waiting on you and the launch moved to Friday.").
- **Preheader:** ~90 characters shown in the inbox preview, based on the TL;DR.
- **Greeting:** "Good morning/afternoon/evening, {first name}" by local time.

HTML-escape all mail-derived text (`&`, `<`, `>`, `"`). Never paste raw email
HTML into the digest.

## Step 5 — Render and send

### Pick a theme

| Theme       | Look                                                                 | Template                                             |
| ----------- | -------------------------------------------------------------------- | ---------------------------------------------------- |
| `midnight`  | Default. Dark Wazzup hero with stats, light cards with accent rails  | [templates/midnight.html](templates/midnight.html)   |
| `editorial` | Warm paper, serif headlines, numbered stories, dark quick-hits panel | [templates/editorial.html](templates/editorial.html) |

Use `midnight` unless the user asks for `editorial` (for example "editorial
style", "newspaper look", or "weekend edition"). Read the chosen template file
from this skill's folder and fill it in; do not redesign it.

### Fill the template

Each template marks repeatable blocks with HTML comments. Repeat
`<!-- HIGHLIGHT -->…<!-- /HIGHLIGHT -->` once per featured highlight and
`<!-- QUICK HIT -->…<!-- /QUICK HIT -->` once per quick hit. Remove the whole
`<!-- QUICK HITS -->…<!-- /QUICK HITS -->` section when there are none. In
`editorial`, drop the `<!-- DIVIDER -->` row before the first highlight. Strip
the marker comments from the final HTML.

| Placeholder                     | Value                                                                                                 |
| ------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `{{PREHEADER}}`                 | Preheader text                                                                                        |
| `{{DATE_LABEL}}`                | `Saturday 14 November` (`midnight`), `Sat 14 Nov 2026` (`editorial`)                                  |
| `{{GREETING}}`                  | Greeting line                                                                                         |
| `{{TLDR}}`                      | TL;DR sentence                                                                                        |
| `{{STAT_SCANNED}}`              | Emails scanned after paging                                                                           |
| `{{STAT_NEEDS_YOU}}`            | Featured items in `NEEDS YOU`                                                                         |
| `{{STAT_DEADLINES}}`            | Featured items in `DEADLINE`                                                                          |
| `{{WINDOW_LABEL}}`              | Window, for example `Fri 07:00 – Sat 08:00`                                                           |
| `{{INDEX}}`                     | `editorial` only: `01`, `02`, …                                                                       |
| `{{CATEGORY}}`                  | `NEEDS YOU`, `DEADLINE`, `DECISION`, or `FYI`                                                         |
| `{{ACCENT}}`                    | Category accent for the chosen theme (table below)                                                    |
| `{{HEADLINE}}` / `{{SUMMARY}}`  | Highlight headline and summary                                                                        |
| `{{NEXT_STEP}}`                 | Next step; in `editorial` it is the link text, so use "Read the thread" instead of "No action needed" |
| `{{SENDER}}` / `{{WHEN}}`       | Sender display name and relative time                                                                 |
| `{{WEBLINK}}`                   | Message `webLink`                                                                                     |
| `{{QH_SENDER}}` / `{{QH_TEXT}}` | Quick hit sender and one-liner                                                                        |
| `{{QH_WEBLINK}}`                | Quick hit message `webLink`                                                                           |

| Category    | `midnight` accent | `editorial` accent |
| ----------- | ----------------- | ------------------ |
| `NEEDS YOU` | `#e11d48`         | `#c2410c`          |
| `DEADLINE`  | `#d97706`         | `#b45309`          |
| `DECISION`  | `#7c3aed`         | `#6d28d9`          |
| `FYI`       | `#0891b2`         | `#0e7490`          |

Rendering rules: keep the template's table-based layout and inline styles so
it renders in Outlook desktop, Outlook on the web, mobile, and Gmail. Never add
JavaScript, external CSS, web fonts, or remote images.

### "All quiet" variant

When nothing is worth highlighting, set `{{TLDR}}` to "Nothing needs you right
now. Enjoy the calm.", remove every highlight and the quick-hits section, and
keep the header, stats, and footer.

### Send

Send it as HTML (`contentType: HTML`) to the user's own address with subject:

```text
Wazzup · {Weekday d MMM} · {n} need you
```

Use `Wazzup · {Weekday d MMM} · All quiet` when nothing needs the user. With
Graph, use `POST /me/sendMail` with `saveToSentItems: true` so the next run
can find the window start.

After sending, reply in chat with one line: how many emails were scanned, how
many highlights were sent, the theme, and the subject line. Do not repeat the
digest.

## Installing

- **GitHub Copilot (CLI / VS Code):** discovered automatically from
  `.github/skills/wazzup-mail-highlights/` in this repository. Copy the folder
  to `~/.copilot/skills/` to use it in other repositories.
- **Microsoft 365 Copilot Cowork:** copy the whole `wazzup-mail-highlights`
  folder (including `templates/`) to OneDrive at
  `/Documents/Cowork/skills/wazzup-mail-highlights/`, or upload it from
  Cowork's Customize page.
