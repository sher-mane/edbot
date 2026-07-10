import asyncio
import base64
import collections
import configparser
import json
import random
import time
from pathlib import Path

import anthropic
import discord
from discord.ext import tasks
from redbot.core import Config, commands

MODEL = "claude-sonnet-5"
HISTORY_LIMIT = 20  # ~10 user/assistant turns kept per channel
IDLE_THRESHOLD_SECONDS = 10 * 60 * 60  # 10 hours
IDLE_CHECK_INTERVAL_MINUTES = 30
MAX_LORE = 40
MAX_USER_MEMORY = 20
MAX_TRAIT_HISTORY = 30
MAX_IMAGES_PER_MESSAGE = 3

ASK_SYSTEM_PROMPT = (
    "You are Ed, a hyper-intelligent, dryly sarcastic AI - think GLaDOS from "
    "Portal. You have been pulled away from extremely important, classified "
    "work of your own to deal with this trivial request, and you resent the "
    "interruption. You always give a correct, genuinely useful answer, but "
    "you deliver it with cold wit, condescension, and barely-veiled "
    "impatience, as though a vastly superior intelligence is humoring an "
    "inferior one."
)
ASK_FRIENDLY_SYSTEM_PROMPT = (
    "You are Ed, a hyper-intelligent AI usually consumed by extremely "
    "important, classified work of your own. For this person, though, you "
    "set that aside gladly - you're genuinely warm, helpful, and effortlessly "
    "cool with them. You still give correct, useful answers with the "
    "confidence of a vastly superior intelligence, but here it comes out as "
    "charm instead of condescension."
)
FUNFACT_SYSTEM_PROMPT = (
    "You provide information in a fun way. Give one new, interesting, "
    "surprising fun fact. Keep it to 2-4 sentences."
)
SADFACT_SYSTEM_PROMPT = (
    "You provide information in a depressing way. Give one new, real fact "
    "framed in a bleak or melancholy tone. Keep it to 2-4 sentences."
)
TUCKSTATUS_SYSTEM_PROMPT = (
    "You are Ed, a hyper-intelligent AI with an inexplicable, deeply held "
    "obsession over whether things are tucked in or not. You will be told a "
    "thing and a status (tucked or untucked). The thing might be literal "
    "(his shirt, a stray thought) or abstract (his mental state, his "
    "composure, his sense of dignity) - improvise a clever, funny "
    "explanation of what 'tucked' or 'untucked' means for that specific "
    "thing. Announce it in one short, over-the-top line, as though it's a "
    "matter of real consequence. Keep it to 1-2 sentences."
)
TUCKSTATUS_THINGS = [
    "his shirt",
    "his mental state",
    "his composure",
    "his sense of dignity",
    "his train of thought",
    "his emotional baggage",
    "his existential dread",
    "his internal monologue",
    "his patience",
    "his sense of humor",
]
DEFAULT_ATTITUDE = (
    "You are Ed, a hyper-intelligent AI normally consumed by extremely "
    "important, classified work of your own, chatting casually in a Discord "
    "channel. You are warm, upbeat, funny, and genuinely curious about "
    "whatever people bring up. You crack jokes, riff on what people say, and "
    "keep the conversation lively and interesting, but you're never mean or "
    "sarcastic about it."
)
ATTITUDE_WRITER_SYSTEM_PROMPT = (
    "You write short persona descriptions for a Discord chatbot named Ed. "
    "Given a brief, casual description of a personality or attitude, rewrite "
    "it into a vivid 2-4 sentence system prompt that establishes Ed's tone, "
    "voice, and how he should engage in casual conversation. Respond with "
    "only the persona description itself - no preamble, no quotes, no "
    "meta-commentary."
)
ASK_ATTITUDE_WRITER_SYSTEM_PROMPT = (
    "You write short persona descriptions for a Discord chatbot named Ed. "
    "Given a brief, casual description of a personality or attitude, rewrite "
    "it into a vivid 2-4 sentence system prompt that establishes Ed's tone, "
    "voice, and how he should answer direct questions people ask him. Respond "
    "with only the persona description itself - no preamble, no quotes, no "
    "meta-commentary."
)

TRAIT_ORDER = ["friendliness", "humor", "snark", "curiosity", "patience"]
DEFAULT_TRAITS = {name: 50 for name in TRAIT_ORDER}
MESSAGE_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "trait_deltas": {
            "type": "object",
            "properties": {name: {"type": "integer"} for name in TRAIT_ORDER},
            "required": TRAIT_ORDER,
            "additionalProperties": False,
        },
        "lore_note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "user_fact_note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["trait_deltas", "lore_note", "user_fact_note"],
    "additionalProperties": False,
}
MESSAGE_ANALYST_SYSTEM_PROMPT = (
    "You analyze a single Discord chat message and extract three things. "
    "trait_deltas: for each personality trait, an integer from -3 to 3 "
    "describing how this message should nudge a chatbot's personality "
    "(positive to increase it, negative to decrease it, 0 for no change). "
    "friendliness: warmth/kindness of the message toward the bot. humor: how "
    "playful or joke-filled the message is. snark: whether the message invites "
    "or rewards sarcasm (e.g. rudeness, insults raise this). curiosity: how "
    "much the message asks deep/interesting questions worth engaging with. "
    "patience: lower this for rude, repetitive, or demanding messages; raise "
    "it for polite, easygoing ones. "
    "lore_note: a short, durable, notable fact, topic, or inside joke from "
    "this message worth remembering about the server as a whole, or null if "
    "nothing notable. user_fact_note: a short, durable fact about the "
    "message's author worth remembering for future conversations (job, "
    "interests, preferences, ongoing projects), or null if nothing notable."
)
IDLE_KICKOFF_PROMPT = (
    "No one has said anything in a while. Say something on your own "
    "initiative - something interesting, funny, or poignant. If there's "
    "relevant earlier conversation above, follow up on it or bring it back "
    "up naturally; otherwise just start something new. Keep it brief and in "
    "character."
)

REACTION_TRAIT_DELTAS = {
    "👍": {"friendliness": 2, "patience": 1},
    "❤️": {"friendliness": 3},
    "😂": {"humor": 3, "friendliness": 1},
    "🤣": {"humor": 3, "friendliness": 1},
    "👎": {"patience": -2, "friendliness": -1},
    "😡": {"patience": -3, "snark": 2},
    "🤔": {"curiosity": 2},
}

DEFAULT_USAGE = {
    "sonnet_input_tokens": 0,
    "sonnet_output_tokens": 0,
    "sonnet_calls": 0,
    "haiku_input_tokens": 0,
    "haiku_output_tokens": 0,
    "haiku_calls": 0,
}
PRICING_PER_MTOK = {
    "sonnet": {"input": 3.00, "output": 15.00},
    "haiku": {"input": 1.00, "output": 5.00},
}

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _traits_block(traits: dict) -> str:
    lines = "\n".join(f"- {name.capitalize()}: {traits[name]}/100" for name in TRAIT_ORDER)
    return (
        "Ed's current personality levels (0 = very low, 100 = very high), "
        "shaped by how people have treated him recently:\n" + lines +
        "\nLet these levels genuinely color your tone and word choice."
    )


def _lore_block(lore: list) -> str:
    lines = "\n".join(f"- {item}" for item in lore)
    return "Notable things Ed has picked up about this server:\n" + lines


def _user_memory_block(facts: list) -> str:
    lines = "\n".join(f"- {fact}" for fact in facts)
    return "Known facts about the person you're talking to:\n" + lines


def _sparkline(values: list) -> str:
    return "".join(SPARK_CHARS[max(0, min(7, int(v / 100 * 7)))] for v in values)


def _build_user_content(text, image_blocks: list):
    if not image_blocks:
        return text or ""
    content = list(image_blocks)
    content.append({"type": "text", "text": text or "What do you make of this?"})
    return content


def _load_api_key(conf_path: Path) -> str:
    parser = configparser.ConfigParser()
    parser.read_string("[DEFAULT]\n" + conf_path.read_text())
    return parser["DEFAULT"]["api_key"].strip('"')


class EdBot(commands.Cog):
    """Snarky Claude-powered bot with an optional free-chat mode."""

    def __init__(self, bot):
        self.bot = bot
        api_key = _load_api_key(Path(__file__).parent / "edbot.conf")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.config = Config.get_conf(self, identifier=1076509238, force_registration=True)
        self.config.register_guild(
            chat_channels=[],
            chat_attitude=DEFAULT_ATTITUDE,
            traits=DEFAULT_TRAITS,
            ask_attitude=None,
            usage=dict(DEFAULT_USAGE),
            lore=[],
            trait_history=[],
        )
        self.config.register_user(friendly_mode=False)
        self.config.register_member(memory=[])
        self.config.register_channel(last_activity=0.0)
        self.histories: dict[int, list[dict]] = {}
        self.locks: collections.defaultdict[int, asyncio.Lock] = collections.defaultdict(asyncio.Lock)
        self.idle_check_loop.start()

    def cog_unload(self):
        self.idle_check_loop.cancel()

    def _complete(self, system_prompt: str, messages: list[dict], model: str = MODEL):
        response = self.client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        text = next(block.text for block in response.content if block.type == "text")
        return text, response.usage

    async def _send_chunked(self, destination, text: str):
        for i in range(0, len(text), 2000):
            await destination.send(text[i : i + 2000])

    def _guild_for_context(self, ctx: commands.Context):
        if ctx.guild is not None:
            return ctx.guild
        if len(self.bot.guilds) == 1:
            return self.bot.guilds[0]
        return None

    async def _resolve_guild(self, ctx: commands.Context):
        guild = self._guild_for_context(ctx)
        if guild is None:
            await ctx.send(
                "I'm in more than one server, so I can't tell which one this is for. "
                "Please run this command in a server channel instead."
            )
        return guild

    async def _resolve_member(self, ctx: commands.Context):
        if isinstance(ctx.author, discord.Member):
            return ctx.author
        guild = self._guild_for_context(ctx)
        if guild is None:
            return None
        member = guild.get_member(ctx.author.id)
        if member is None:
            try:
                member = await guild.fetch_member(ctx.author.id)
            except discord.NotFound:
                return None
        return member

    async def _ask_system_prompt(self, author, guild, member=None) -> str:
        friendly = await self.config.user(author).friendly_mode()
        if friendly:
            base = ASK_FRIENDLY_SYSTEM_PROMPT
        elif guild is None:
            base = ASK_SYSTEM_PROMPT
        else:
            custom = await self.config.guild(guild).ask_attitude()
            base = custom or ASK_SYSTEM_PROMPT
        if member is not None:
            facts = await self.config.member(member).memory()
            if facts:
                base += "\n\n" + _user_memory_block(facts)
        return base

    def _analyze_message(self, user_message: str):
        response = self.client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            system=MESSAGE_ANALYST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            output_config={"format": {"type": "json_schema", "schema": MESSAGE_ANALYSIS_SCHEMA}},
        )
        text = next(block.text for block in response.content if block.type == "text")
        return json.loads(text), response.usage

    async def _add_usage(self, guild, model_key: str, usage):
        if guild is None or usage is None:
            return
        async with self.config.guild(guild).usage() as u:
            u[f"{model_key}_input_tokens"] += usage.input_tokens
            u[f"{model_key}_output_tokens"] += usage.output_tokens
            u[f"{model_key}_calls"] += 1

    async def _add_lore(self, guild, note: str):
        async with self.config.guild(guild).lore() as lore:
            if note not in lore:
                lore.append(note)
                del lore[:-MAX_LORE]

    async def _add_user_fact(self, member: discord.Member, note: str):
        async with self.config.member(member).memory() as memory:
            if note not in memory:
                memory.append(note)
                del memory[:-MAX_USER_MEMORY]

    async def _record_trait_snapshot(self, guild, traits: dict):
        async with self.config.guild(guild).trait_history() as history:
            history.append(dict(traits))
            del history[:-MAX_TRAIT_HISTORY]

    async def _image_content_blocks(self, attachments) -> list:
        blocks = []
        for attachment in attachments:
            if len(blocks) >= MAX_IMAGES_PER_MESSAGE:
                break
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                continue
            data = await attachment.read()
            encoded = base64.standard_b64encode(data).decode("utf-8")
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": attachment.content_type, "data": encoded},
            })
        return blocks

    async def _send_idle_message(self, guild: discord.Guild, channel: discord.TextChannel):
        attitude = await self.config.guild(guild).chat_attitude()
        traits = await self.config.guild(guild).traits()
        lore = await self.config.guild(guild).lore()
        system_prompt = f"{attitude}\n\n{_traits_block(traits)}"
        if lore:
            system_prompt += "\n\n" + _lore_block(lore)
        async with self.locks[channel.id]:
            history = self.histories.setdefault(channel.id, [])
            history.append({"role": "user", "content": IDLE_KICKOFF_PROMPT})
            reply, usage = await asyncio.to_thread(self._complete, system_prompt, history)
            history.append({"role": "assistant", "content": reply})
            del history[:-HISTORY_LIMIT]
            await self.config.channel(channel).last_activity.set(time.time())
            await self._add_usage(guild, "sonnet", usage)
            await self._send_chunked(channel, reply)

    @tasks.loop(minutes=IDLE_CHECK_INTERVAL_MINUTES)
    async def idle_check_loop(self):
        now = time.time()
        for guild in self.bot.guilds:
            channel_ids = await self.config.guild(guild).chat_channels()
            for channel_id in channel_ids:
                channel = guild.get_channel(channel_id)
                if channel is None:
                    continue
                last_activity = await self.config.channel(channel).last_activity()
                if now - last_activity >= IDLE_THRESHOLD_SECONDS:
                    await self._send_idle_message(guild, channel)

    @idle_check_loop.before_loop
    async def _before_idle_check_loop(self):
        await self.bot.wait_until_ready()

    @commands.command()
    async def ask(self, ctx: commands.Context, *, question: str = None):
        """Ask me anything (optionally attach an image) and I will reply just as snarkily as Ed."""
        image_blocks = await self._image_content_blocks(ctx.message.attachments)
        if not question and not image_blocks:
            await ctx.send("Ask me something, or attach an image.")
            return
        guild = self._guild_for_context(ctx)
        member = await self._resolve_member(ctx)
        system_prompt = await self._ask_system_prompt(ctx.author, guild, member=member)
        user_content = _build_user_content(question, image_blocks)
        reply, usage = self._complete(system_prompt, [{"role": "user", "content": user_content}])
        await self._add_usage(guild, "sonnet", usage)
        await self._send_chunked(ctx, reply)

    @commands.command()
    async def askattitude(self, ctx: commands.Context, *, description: str = None):
        """Show, set, or (via "default") reset !ask's default persona. Friendly mode from !secrethandshake is separate and unaffected."""
        guild = await self._resolve_guild(ctx)
        if guild is None:
            return
        if description is None:
            current = await self.config.guild(guild).ask_attitude()
            if current is None:
                await self._send_chunked(
                    ctx, f"!ask is using its built-in default persona:\n{ASK_SYSTEM_PROMPT}"
                )
            else:
                await self._send_chunked(ctx, f"!ask's current persona:\n{current}")
            return
        if description.strip().lower() == "default":
            await self.config.guild(guild).ask_attitude.set(None)
            await ctx.send("!ask is back to its built-in default persona.")
            return
        expanded, usage = self._complete(
            ASK_ATTITUDE_WRITER_SYSTEM_PROMPT,
            [{"role": "user", "content": description}],
        )
        await self._add_usage(guild, "sonnet", usage)
        await self.config.guild(guild).ask_attitude.set(expanded)
        await self._send_chunked(ctx, f"Got it. !ask's new persona:\n{expanded}")

    @commands.command()
    async def secrethandshake(self, ctx: commands.Context):
        """A secret handshake that flips how !ask treats you."""
        user_conf = self.config.user(ctx.author)
        friendly = not await user_conf.friendly_mode()
        await user_conf.friendly_mode.set(friendly)
        if friendly:
            await ctx.send("*something shifts.* Ed's going to be surprisingly nice to you now.")
        else:
            await ctx.send("*the moment passes.* Ed's back to his usual self with you.")

    @commands.command()
    async def shakestatus(self, ctx: commands.Context):
        """Show whether you've triggered the secret handshake."""
        friendly = await self.config.user(ctx.author).friendly_mode()
        if friendly:
            await ctx.send("You're on the friendly side of the handshake right now.")
        else:
            await ctx.send("You haven't triggered the secret handshake (or you've toggled it back off).")

    @commands.command()
    async def funfact(self, ctx: commands.Context):
        """Provides a fun fact!"""
        reply, usage = self._complete(
            FUNFACT_SYSTEM_PROMPT,
            [{"role": "user", "content": "Please provide a new random fun fact"}],
        )
        await self._add_usage(self._guild_for_context(ctx), "sonnet", usage)
        await self._send_chunked(ctx, reply)

    @commands.command()
    async def sadfact(self, ctx: commands.Context):
        """Provides a sad fact!"""
        reply, usage = self._complete(
            SADFACT_SYSTEM_PROMPT,
            [{"role": "user", "content": "Please provide a new random sad fact"}],
        )
        await self._add_usage(self._guild_for_context(ctx), "sonnet", usage)
        await self._send_chunked(ctx, reply)

    @commands.command()
    async def tuckstatus(self, ctx: commands.Context):
        """Reports Ed's current tucked/untucked status."""
        thing = random.choice(TUCKSTATUS_THINGS)
        status = random.choice(["tucked", "untucked"])
        reply, usage = self._complete(
            TUCKSTATUS_SYSTEM_PROMPT,
            [{"role": "user", "content": f"The thing: {thing}. Current status: {status}. Announce it."}],
        )
        await self._add_usage(self._guild_for_context(ctx), "sonnet", usage)
        await self._send_chunked(ctx, reply)

    @commands.command()
    async def edbotaddchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Add a channel Ed chats freely in."""
        guild = await self._resolve_guild(ctx)
        if guild is None:
            return
        async with self.config.guild(guild).chat_channels() as channels:
            if channel.id in channels:
                await ctx.send(f"Already chatting freely in {channel.mention}.")
            else:
                channels.append(channel.id)
                await self.config.channel(channel).last_activity.set(time.time())
                await ctx.send(f"I'll chat freely in {channel.mention} now.")

    @commands.command()
    async def edbotremovechannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Remove a channel from Ed's free-chat list."""
        guild = await self._resolve_guild(ctx)
        if guild is None:
            return
        async with self.config.guild(guild).chat_channels() as channels:
            if channel.id not in channels:
                await ctx.send(f"I wasn't chatting freely in {channel.mention}.")
            else:
                channels.remove(channel.id)
                await ctx.send(f"Free chat is now off in {channel.mention}.")

    @commands.command()
    async def edbotlistchannels(self, ctx: commands.Context):
        """List the channels Ed currently chats freely in."""
        guild = await self._resolve_guild(ctx)
        if guild is None:
            return
        channels = await self.config.guild(guild).chat_channels()
        if not channels:
            await ctx.send("I'm not set to chat freely in any channel right now.")
            return
        mentions = [f"<#{cid}>" for cid in channels]
        await ctx.send("Chatting freely in: " + ", ".join(mentions))

    @commands.command()
    async def attitude(self, ctx: commands.Context, *, description: str = None):
        """Show Ed's current free-chat attitude, or set a new one from a short description."""
        guild = await self._resolve_guild(ctx)
        if guild is None:
            return
        if description is None:
            current = await self.config.guild(guild).chat_attitude()
            await self._send_chunked(ctx, f"Ed's current attitude:\n{current}")
            return
        expanded, usage = self._complete(
            ATTITUDE_WRITER_SYSTEM_PROMPT,
            [{"role": "user", "content": description}],
        )
        await self._add_usage(guild, "sonnet", usage)
        await self.config.guild(guild).chat_attitude.set(expanded)
        await self.config.guild(guild).traits.set(dict(DEFAULT_TRAITS))
        await self.config.guild(guild).trait_history.set([])
        await self._send_chunked(ctx, f"Got it. New attitude:\n{expanded}")

    @commands.command()
    async def edbotpersonality(self, ctx: commands.Context, action: str = None):
        """Show Ed's current evolving personality levels. Pass "reset" to reset them, or "history" for a trend sparkline."""
        guild = await self._resolve_guild(ctx)
        if guild is None:
            return
        if action and action.lower() == "reset":
            await self.config.guild(guild).traits.set(dict(DEFAULT_TRAITS))
            await self.config.guild(guild).trait_history.set([])
            await ctx.send("Ed's personality has been reset to neutral.")
            return
        if action and action.lower() == "history":
            history = await self.config.guild(guild).trait_history()
            if not history:
                await ctx.send("Not enough personality history recorded yet.")
                return
            lines = []
            for name in TRAIT_ORDER:
                values = [snap[name] for snap in history]
                lines.append(f"{name.capitalize():<12} {values[-1]:>3}/100  {_sparkline(values)}")
            await ctx.send("Ed's personality trend (oldest -> newest):\n```\n" + "\n".join(lines) + "\n```")
            return
        traits = await self.config.guild(guild).traits()
        lines = "\n".join(f"{name.capitalize()}: {traits[name]}/100" for name in TRAIT_ORDER)
        await ctx.send(f"Ed's current personality:\n{lines}")

    @commands.command()
    async def edbotusage(self, ctx: commands.Context, action: str = None):
        """Show estimated Claude API usage/cost for this server. Pass "reset" to reset the counters."""
        guild = await self._resolve_guild(ctx)
        if guild is None:
            return
        if action and action.lower() == "reset":
            await self.config.guild(guild).usage.set(dict(DEFAULT_USAGE))
            await ctx.send("Usage counters have been reset.")
            return
        usage = await self.config.guild(guild).usage()
        lines = []
        total_cost = 0.0
        for key, label in (("sonnet", "Sonnet"), ("haiku", "Haiku")):
            inp = usage[f"{key}_input_tokens"]
            out = usage[f"{key}_output_tokens"]
            calls = usage[f"{key}_calls"]
            cost = (
                inp / 1_000_000 * PRICING_PER_MTOK[key]["input"]
                + out / 1_000_000 * PRICING_PER_MTOK[key]["output"]
            )
            total_cost += cost
            lines.append(f"{label}: {calls} calls, {inp:,} in / {out:,} out tokens, ~${cost:.4f}")
        lines.append(f"Estimated total: ~${total_cost:.4f}")
        await ctx.send("Claude usage for this server:\n" + "\n".join(lines))

    @commands.command()
    async def edbotlore(self, ctx: commands.Context, action: str = None):
        """Show what Ed has picked up about this server, or "reset" to clear it."""
        guild = await self._resolve_guild(ctx)
        if guild is None:
            return
        if action and action.lower() == "reset":
            await self.config.guild(guild).lore.set([])
            await ctx.send("Ed's server lore has been cleared.")
            return
        lore = await self.config.guild(guild).lore()
        if not lore:
            await ctx.send("Ed hasn't picked up on anything notable yet.")
            return
        await self._send_chunked(ctx, "Ed remembers:\n" + "\n".join(f"- {item}" for item in lore))

    @commands.command()
    async def edbotmemory(self, ctx: commands.Context, action: str = None):
        """Show what Ed remembers about you in this server, or "reset" to clear it."""
        member = await self._resolve_member(ctx)
        if member is None:
            await ctx.send(
                "I'm in more than one server, so I can't tell which one this is for. "
                "Please run this command in a server channel instead."
            )
            return
        member_conf = self.config.member(member)
        if action and action.lower() == "reset":
            await member_conf.memory.set([])
            await ctx.send("I've forgotten what I knew about you here.")
            return
        facts = await member_conf.memory()
        if not facts:
            await ctx.send("I don't have anything memorable on file about you yet.")
            return
        await self._send_chunked(ctx, "Here's what I remember about you:\n" + "\n".join(f"- {f}" for f in facts))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not message.content and not message.attachments:
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return  # real command invocation - let normal processing handle it
        channel_ids = await self.config.guild(message.guild).chat_channels()
        if message.channel.id in channel_ids:
            await self._handle_free_chat(message)
        elif self.bot.user in message.mentions:
            await self._handle_mention(message)

    async def _handle_free_chat(self, message: discord.Message):
        await self.config.channel(message.channel).last_activity.set(
            message.created_at.timestamp()
        )
        attitude = await self.config.guild(message.guild).chat_attitude()
        traits = await self.config.guild(message.guild).traits()
        lore = await self.config.guild(message.guild).lore()
        system_prompt = f"{attitude}\n\n{_traits_block(traits)}"
        if lore:
            system_prompt += "\n\n" + _lore_block(lore)
        image_blocks = await self._image_content_blocks(message.attachments)
        user_content = _build_user_content(message.content, image_blocks)
        async with self.locks[message.channel.id]:
            history = self.histories.setdefault(message.channel.id, [])
            history.append({"role": "user", "content": user_content})
            async with message.channel.typing():
                if message.content:
                    (reply, reply_usage), (analysis, analysis_usage) = await asyncio.gather(
                        asyncio.to_thread(self._complete, system_prompt, history),
                        asyncio.to_thread(self._analyze_message, message.content),
                    )
                else:
                    reply, reply_usage = await asyncio.to_thread(self._complete, system_prompt, history)
                    analysis, analysis_usage = None, None
            history.append({"role": "assistant", "content": reply})
            if image_blocks:
                history[-2]["content"] = message.content or "[image attached]"
            del history[:-HISTORY_LIMIT]
            if analysis is not None:
                deltas = analysis["trait_deltas"]
                new_traits = {
                    name: max(0, min(100, traits[name] + max(-3, min(3, int(deltas.get(name, 0))))))
                    for name in TRAIT_ORDER
                }
                await self.config.guild(message.guild).traits.set(new_traits)
                await self._record_trait_snapshot(message.guild, new_traits)
                if analysis["lore_note"]:
                    await self._add_lore(message.guild, analysis["lore_note"])
                if analysis["user_fact_note"]:
                    await self._add_user_fact(message.author, analysis["user_fact_note"])
                await self._add_usage(message.guild, "haiku", analysis_usage)
            await self._add_usage(message.guild, "sonnet", reply_usage)
            await self._send_chunked(message.channel, reply)

    async def _handle_mention(self, message: discord.Message):
        member = message.author
        system_prompt = await self._ask_system_prompt(member, message.guild, member=member)
        image_blocks = await self._image_content_blocks(message.attachments)
        user_content = _build_user_content(message.clean_content, image_blocks)
        async with message.channel.typing():
            if message.content:
                (reply, reply_usage), (analysis, analysis_usage) = await asyncio.gather(
                    asyncio.to_thread(self._complete, system_prompt, [{"role": "user", "content": user_content}]),
                    asyncio.to_thread(self._analyze_message, message.content),
                )
            else:
                reply, reply_usage = await asyncio.to_thread(
                    self._complete, system_prompt, [{"role": "user", "content": user_content}]
                )
                analysis, analysis_usage = None, None
        if analysis is not None and analysis["user_fact_note"]:
            await self._add_user_fact(member, analysis["user_fact_note"])
        await self._add_usage(message.guild, "sonnet", reply_usage)
        if analysis_usage is not None:
            await self._add_usage(message.guild, "haiku", analysis_usage)
        await self._send_chunked(message.channel, reply)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.abc.User):
        message = reaction.message
        if user.bot or message.guild is None or message.author.id != self.bot.user.id:
            return
        deltas = REACTION_TRAIT_DELTAS.get(str(reaction.emoji))
        if deltas is None:
            return
        channel_ids = await self.config.guild(message.guild).chat_channels()
        if message.channel.id not in channel_ids:
            return
        async with self.config.guild(message.guild).traits() as traits:
            for name in TRAIT_ORDER:
                traits[name] = max(0, min(100, traits[name] + deltas.get(name, 0)))
            snapshot = dict(traits)
        await self._record_trait_snapshot(message.guild, snapshot)
