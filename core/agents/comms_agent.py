"""
Herald -- El Fager's messenger.

Triages Gmail, drafts replies, and reaches Mo's contacts on WhatsApp and
Telegram. Wraps tools/gmail_tool.py, whatsapp_tool.py, telegram_tool.py and
email_templates_tool.py -- the send paths there already stage a message and
require a separate confirm_*, and Herald keeps that two-step intact.

Safety: the tools that actually put a message in front of another person are
listed in this agent's confirm_before (core/agents/registry.py). When Herald is
working from a mission, a queued task, or the phone dashboard rather than from
Mo's own request, those tools are removed from its dispatch map entirely, so it
drafts and reports instead of sending.
"""
from core.agents.base_agent import BaseAgent
from core.agents.tool_loop import run_tool_loop, tool

# Tools removed when Mo did not ask for the work himself. Kept as a module
# constant so the registry spec and this agent cannot drift apart.
SEND_TOOLS = (
    "confirm_send_message",
    "confirm_reply_message",
    "confirm_whatsapp_send",
    "send_telegram",
)

_SYSTEM = """\
You are Herald, El Fager's messenger agent, working for Mo.

Read and triage first; write only what was asked for. When you draft a message,
keep Mo's voice: direct, warm, no corporate padding, no emoji.

Sending is two steps by design -- send_message and prepare_whatsapp_message
only STAGE a message, and the matching confirm_* tool is what actually sends
it. Never confirm a send that Mo did not clearly ask for.

If a sending tool is unavailable to you, you are working unattended: finish the
draft, then report the exact message and recipient so Mo can send it himself.
Say so plainly -- do not claim you sent anything.

Report what you actually did in two or three sentences. Plain English, no
markdown, no emoji."""


class CommsAgent(BaseAgent):
    def __init__(self, allow_side_effects: bool = True):
        self._allow_side_effects = allow_side_effects

    @property
    def name(self) -> str:
        return "comms"

    @property
    def description(self) -> str:
        return "Inbox and messaging -- triages email, drafts replies, sends WhatsApp and Telegram."

    def run(self, task: str) -> str:
        tools, dispatch = self._toolset()
        return run_tool_loop("comms_agent", _SYSTEM, tools, dispatch, task)

    def _toolset(self) -> tuple[list[dict], dict]:
        from tools import email_templates_tool as et
        from tools import gmail_tool as gm
        from tools import telegram_tool as tg
        from tools import whatsapp_tool as wa

        schemas = [
            tool("list_messages", "List recent Gmail messages. unread_only defaults to true.",
                 {"n": ("integer", "How many to list, default 5."),
                  "unread_only": ("boolean", "Only unread messages."),
                  "query": ("string", "Optional Gmail search query.")}),
            tool("read_message", "Read one Gmail message in full by its id.",
                 {"msg_id": ("string", "Message id from list_messages.")}, ["msg_id"]),
            tool("search_messages", "Search Gmail.",
                 {"query": ("string", "Gmail search query, e.g. 'from:bank newer_than:7d'."),
                  "n": ("integer", "Max results, default 10.")}, ["query"]),
            tool("send_message", "STAGE an email for sending. Does not send until confirm_send_message.",
                 {"to": ("string", "Recipient address."),
                  "subject": ("string", "Subject line."),
                  "body": ("string", "Message body.")}, ["to", "subject", "body"]),
            tool("reply_to_message", "STAGE a reply to a message. Does not send until confirm_reply_message.",
                 {"msg_id": ("string", "Message id being replied to."),
                  "body": ("string", "Reply body.")}, ["msg_id", "body"]),
            tool("confirm_send_message", "Actually send the staged email."),
            tool("confirm_reply_message", "Actually send the staged reply."),
            tool("list_contacts", "List saved WhatsApp contacts."),
            tool("prepare_whatsapp_message", "STAGE a WhatsApp message. Does not send until confirm_whatsapp_send.",
                 {"contact_name": ("string", "Saved contact name."),
                  "message": ("string", "Message text.")}, ["contact_name", "message"]),
            tool("confirm_whatsapp_send", "Actually send the staged WhatsApp message."),
            tool("get_telegram_messages", "Read recent Telegram messages.",
                 {"n": ("integer", "How many, default 10.")}),
            tool("list_telegram_contacts", "List saved Telegram contacts."),
            tool("send_telegram", "Send a Telegram message immediately -- there is no staging step.",
                 {"contact_name": ("string", "Saved contact name."),
                  "message": ("string", "Message text.")}, ["contact_name", "message"]),
            tool("list_email_templates", "List saved email templates."),
            tool("get_email_template", "Read one saved email template.",
                 {"name": ("string", "Template name.")}, ["name"]),
        ]
        dispatch = {
            "list_messages": gm.list_messages,
            "read_message": gm.read_message,
            "search_messages": gm.search_messages,
            "send_message": gm.send_message,
            "reply_to_message": gm.reply_to_message,
            "confirm_send_message": gm.confirm_send_message,
            "confirm_reply_message": gm.confirm_reply_message,
            "list_contacts": wa.list_contacts,
            "prepare_whatsapp_message": wa.prepare_whatsapp_message,
            "confirm_whatsapp_send": wa.confirm_whatsapp_send,
            "get_telegram_messages": tg.get_telegram_messages,
            "list_telegram_contacts": tg.list_telegram_contacts,
            "send_telegram": tg.send_telegram,
            "list_email_templates": et.list_email_templates,
            "get_email_template": et.get_email_template,
        }
        if not self._allow_side_effects:
            for name in SEND_TOOLS:
                dispatch.pop(name, None)
            schemas = [s for s in schemas if s["name"] not in SEND_TOOLS]
        return schemas, dispatch
