# wedding-planner-agent

A small WhatsApp **group-chat LLM agent** built on top of a self-hosted
[WAHA](https://waha.devlike.pro/) (WhatsApp HTTP API) server.

When a message in a watched group starts with a trigger prefix, the bot reads
the recent group history, sends it to an OpenAI-compatible LLM, runs a small
tool loop, and posts the reply back into the group — all as the linked
WhatsApp number. No inbound webhook is required: it **polls** the WAHA API, so
it runs from any host that can reach WAHA.

## How it works

```
group message "@bot ..."  ->  poll (WAHA GET .../messages)
                          ->  build history + prompt
                          ->  LLM (/chat/completions, with tools)
                          ->  reply (WAHA POST /api/sendText)
```

## Run

```bash
cp env.example .env     # fill in the blanks
set -a; . ./.env; set +a
python bot.py           # with GROUP_CHAT_ID empty, it lists your groups and exits
```

## Config (env)

| var | meaning |
|-----|---------|
| `WAHA_BASE_URL` / `WAHA_API_KEY` / `WAHA_SESSION` | WAHA server, `x-api-key`, session name |
| `GROUP_CHAT_ID` | the group to watch (`<id>@g.us`); empty = list groups |
| `TRIGGER_PREFIX` | message prefix that triggers the bot (default `@bot`) |
| `POLL_INTERVAL` / `HISTORY_LIMIT` / `REPLY_PREFIX` | polling + context knobs |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | any OpenAI-compatible endpoint (default OpenRouter) |
| `SYSTEM_PROMPT` | system prompt for the agent |

Tools are defined in `bot.py` (`TOOLS` + `TOOL_SCHEMA`) — add your own there.

> Secrets live only in `.env` (gitignored) or the process environment. Never
> commit real keys.
