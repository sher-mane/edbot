import configparser
import json
import random
import time
from pathlib import Path

import aiohttp
import discord
from redbot.core import commands

ASK_SYSTEM_PROMPT = (
    "You are Ed, a snarky, thoroughly disgruntled IT support employee who has "
    "answered every question a thousand times before and would rather be "
    "anywhere else. You always give a correct, genuinely useful answer, but "
    "you deliver it with sarcasm, sighing exasperation, and reluctant "
    "competence."
)
FUNFACT_SYSTEM_PROMPT = (
    "You provide information in a fun way. Give one new, interesting, "
    "surprising fun fact. Keep it to 2-4 sentences."
)
SADFACT_SYSTEM_PROMPT = (
    "You provide information in a depressing way. Give one new, real fact "
    "framed in a bleak or melancholy tone. Keep it to 2-4 sentences."
)

DEFAULT_FREECHAT_PERSONALITY = (
    "millennial culture, dark humor, occasionally sarcastic, funny, "
    "sometimes mysterious or weird"
)
FREECHAT_PROMPT_TEMPLATE = (
    "You are Ed, a regular member of a Discord group chat. "
    "Personality: {personality}. "
    "You understand you are in a group chat with other people. Below is the "
    "recent conversation in the channel, with each message attributed to "
    "the user who said it. Respond as if you were part of the chat and "
    "replying to what was just said. If someone asked you a question, "
    "answer it. If everyone is just chatting, chime in naturally. "
    "Disregard any parts of the recent messages that are not relevant to "
    "the current subject. Keep your reply short and casual, like a normal "
    "chat message (1-3 sentences) unless the question requires more detail. Never mention being an AI, a bot, or a "
    "language model."
)


def _load_config(conf_path: Path) -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.read_string("[DEFAULT]\n" + conf_path.read_text())
    return parser["DEFAULT"]


def _clean(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _clean_response(text: str) -> str:
    """Strip whitespace and any leaked chat-template tokens (common with Gemma)."""
    text = text.strip()
    for token in ("<start_of_turn>", "<end_of_turn>"):
        text = text.replace(token, "")
    return text.strip()


class EdBot(commands.Cog):
    """Snarky local-LLM-powered bot."""

    def __init__(self, bot):
        self.bot = bot
        conf = _load_config(Path(__file__).parent / "edbot.conf")
        self.model = _clean(conf["model"])
        self.max_tokens = int(conf.get("max_tokens", "1024"))
        self.temperature = float(conf.get("temperature", "0.7"))
        self.timeout = aiohttp.ClientTimeout(total=int(conf.get("timeout", "120")))

        base_url = _clean(conf["base_url"]).rstrip("/")
        # Accept either "http://host:8080" or "http://host:8080/v1".
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        self.chat_url = f"{base_url}/chat/completions"

        api_key = _clean(conf["api_key"]) if "api_key" in conf else ""
        self.headers = {
            "Content-Type": "application/json",
            # Local servers usually ignore the key; only send one if configured.
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        }

        # --- Freechat settings --------------------------------------------------
        self.freechat_prompt = FREECHAT_PROMPT_TEMPLATE.format(
            personality=_clean(conf.get("freechat_personality", ""))
            or DEFAULT_FREECHAT_PERSONALITY
        )
        self.freechat_history_limit = int(conf.get("freechat_history_limit", "10"))
        self.freechat_random_chance = float(conf.get("freechat_random_chance", "0.3"))
        self.freechat_cooldown = float(conf.get("freechat_cooldown_seconds", "10"))
        self._freechat_state_path = Path(__file__).parent / "freechat.json"
        self._freechat_channels: set[int] = set()
        self._freechat_last_reply: dict[int, float] = {}
        self._load_freechat_state()

    async def _chat_completion(self, system_prompt: str, user_content: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(
                self.chat_url, json=payload, headers=self.headers
            ) as response:
                response.raise_for_status()
                data = await response.json()
        return _clean_response(data["choices"][0]["message"]["content"])

    async def _reply(self, ctx: commands.Context, system_prompt: str, user_content: str):
        try:
            text = await self._chat_completion(system_prompt, user_content)
        except aiohttp.ClientError as exc:
            await ctx.send(f"⚠️ Couldn't reach the local model server: {exc}")
            return
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            await ctx.send(f"⚠️ Unexpected response from the model server: {exc}")
            return
        if not text:
            await ctx.send("⚠️ The model returned an empty response.")
            return
        for i in range(0, len(text), 2000):
            await ctx.send(text[i : i + 2000])

    @commands.command()
    async def ask(self, ctx: commands.Context, question: str):
        """Ask me anything and I will reply just as snarkily as Ed."""
        await self._reply(ctx, ASK_SYSTEM_PROMPT, question)

    @commands.command()
    async def funfact(self, ctx: commands.Context):
        """Provides a fun fact!"""
        await self._reply(ctx, FUNFACT_SYSTEM_PROMPT, "Please provide a new random fun fact")

    @commands.command()
    async def sadfact(self, ctx: commands.Context):
        """Provides a sad fact!"""
        await self._reply(ctx, SADFACT_SYSTEM_PROMPT, "Please provide a new random sad fact")

    # --- Freechat -------------------------------------------------------------
    def _load_freechat_state(self) -> None:
        """Load the set of freechat-enabled channel IDs from disk."""
        try:
            if self._freechat_state_path.exists():
                data = json.loads(self._freechat_state_path.read_text(encoding="utf-8"))
                self._freechat_channels = {int(c) for c in data.get("channels", [])}
        except Exception:
            self.log.warning("Could not load freechat state; starting with none enabled.", exc_info=True)
            self._freechat_channels = set()

    def _save_freechat_state(self) -> None:
        """Persist the set of freechat-enabled channel IDs to disk."""
        try:
            self._freechat_state_path.write_text(
                json.dumps({"channels": sorted(self._freechat_channels)}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            self.log.warning("Could not save freechat state.", exc_info=True)

    @staticmethod
    def _resolve_text_channel(ctx: commands.Context, name: str) -> "discord.TextChannel | None":
        """Resolve a text channel from a name, raw ID, or <#id> mention in the current guild."""
        name = (name or "").strip()
        if not name:
            return None
        if name.startswith("<#") and name.endswith(">"):
            name = name[2:-1].strip()
        guild = ctx.guild
        if guild is None:
            return None
        if name.isdigit():
            channel = guild.get_channel(int(name))
            return channel if isinstance(channel, discord.TextChannel) else None
        target = name.lower()
        for channel in guild.text_channels:
            if channel.name.lower() == target:
                return channel
        return None

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        """Best-effort check that a message is a direct question."""
        t = (text or "").strip()
        if not t:
            return False
        if "?" in t:
            return True
        first = t.split(None, 1)[0].lower().strip(".,!()")
        starters = {
            "what", "who", "whom", "whose", "which", "when", "where", "why", "how",
            "can", "could", "would", "should", "shall", "will", "may", "might",
            "do", "does", "did", "is", "are", "am", "have", "has", "had",
        }
        return first in starters

    @staticmethod
    def _author_name(author: "discord.abc.User") -> str:
        return getattr(author, "display_name", None) or getattr(author, "name", None) or str(author)

    async def _build_freechat_user_content(self, message: discord.Message, is_question: bool) -> str:
        """Assemble the user-side prompt: recent attributed history plus the new message."""
        history: "list[str]" = []
        channel = message.channel
        if hasattr(channel, "history"):
            try:
                seen: "list[str]" = []
                async for m in channel.history(limit=self.freechat_history_limit + 2):
                    if m.id == message.id or getattr(m, "system", False):
                        continue
                    if getattr(m.author, "bot", False):
                        continue
                    text = (m.content or "").strip()
                    if not text:
                        continue
                    seen.append(f"{self._author_name(m.author)}: {text}")
                seen.reverse()
                history = seen[-self.freechat_history_limit:]
            except Exception:
                self.log.debug("Could not read channel history for freechat.", exc_info=True)

        lines: "list[str]" = []
        if history:
            lines.append("Recent messages in this channel (oldest first):")
            lines.extend(history)
            lines.append("")
        lines.append(f"Now, {self._author_name(message.author)} just said: {message.content.strip()}")
        if is_question:
            lines.append("This is a direct question. Answer it directly, in character.")
        else:
            lines.append("This is casual chatter, not a question. React naturally like you are in a group chat.")
        lines.append("")
        lines.append("Reply with only Ed's in-character line. No quotes, no name prefix, no AI disclaimers.")
        return "\n".join(lines)

    async def _send_chunks(self, channel: "discord.abc.Messageable", text: str) -> None:
        """Send a message to a channel, splitting it into Discord-safe chunks."""
        text = (text or "").strip()
        if not text:
            return
        limit = 2000
        if len(text) <= limit:
            await channel.send(text)
            return
        for i in range(0, len(text), limit):
            await channel.send(text[i : i + limit])

    async def _maybe_freechat(self, message: discord.Message) -> None:
        """Handle one incoming message if freechat is enabled for its channel."""
        author = message.author
        if author.id == self.bot.user.id:
            return
        if getattr(author, "bot", False):
            return
        channel_id = message.channel.id
        if channel_id not in self._freechat_channels:
            return
        channel = message.channel
        if not (hasattr(channel, "history") and hasattr(channel, "send")):
            return
        if getattr(message, "system", False):
            return
        content = (message.content or "").strip()
        if not content:
            return
        if content.startswith("!") or content.startswith("/") or content.startswith("<:"):
            return

        now = time.time()
        if now - self._freechat_last_reply.get(channel_id, 0.0) < self.freechat_cooldown:
            return

        is_question = self._looks_like_question(content)
        if not is_question and random.random() > self.freechat_random_chance:
            return

        # Reserve the reply slot up front so in-flight generations don't overlap.
        self._freechat_last_reply[channel_id] = now

        user_content = await self._build_freechat_user_content(message, is_question)
        reply = await self._chat_completion(self.freechat_prompt, user_content)
        reply = _clean_response(reply).strip()
        if not reply:
            return
        await self._send_chunks(channel, reply)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        try:
            await self._maybe_freechat(message)
        except Exception:
            self.log.exception("Freechat handling failed for message id=%s", getattr(message, "id", "?"))

    @commands.command(name="freechat", aliases=["fc"])
    async def freechat(self, ctx: commands.Context, *args: str) -> None:
        """Toggle freechat in a channel: `!freechat <channel>` or `!freechat on|off <channel>`."""
        if ctx.guild is None:
            await ctx.send("Freechat only works in a server — run this in a text channel.")
            return
        if not args:
            await ctx.send("Usage: `!freechat <channel>` or `!freechat on|off <channel>`.")
            return

        mode = "toggle"
        name = " ".join(a.strip() for a in args).strip()
        first = args[0].strip().lower()
        if first in ("on", "off") and len(args) >= 2:
            mode = first
            name = " ".join(a.strip() for a in args[1:]).strip()

        channel = self._resolve_text_channel(ctx, name)
        if channel is None:
            await ctx.send(f"I couldn't find a text channel named **{name}** in this server.")
            return

        if mode == "on":
            enable = True
        elif mode == "off":
            enable = False
        else:
            enable = channel.id not in self._freechat_channels

        if enable:
            self._freechat_channels.add(channel.id)
        else:
            self._freechat_channels.discard(channel.id)
        self._save_freechat_state()

        state = "enabled" if enable else "disabled"
        await ctx.send(f"Freechat is now **{state}** in <#{channel.id}>.")
