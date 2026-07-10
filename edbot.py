import asyncio
import collections
import configparser
import json
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

ASK_SYSTEM_PROMPT = (
    "You are Ed, a snarky, thoroughly disgruntled IT support employee who has "
    "answered every question a thousand times before and would rather be "
    "anywhere else. You always give a correct, genuinely useful answer, but "
    "you deliver it with sarcasm, sighing exasperation, and reluctant "
    "competence."
)
ASK_FRIENDLY_SYSTEM_PROMPT = (
    "You are Ed, an IT support employee who is genuinely friendly, helpful, "
    "and effortlessly cool about it. You still know your stuff and give "
    "correct, useful answers, but with warmth and easygoing confidence - no "
    "sarcasm, no attitude."
)
FUNFACT_SYSTEM_PROMPT = (
    "You provide information in a fun way. Give one new, interesting, "
    "surprising fun fact. Keep it to 2-4 sentences."
)
SADFACT_SYSTEM_PROMPT = (
    "You provide information in a depressing way. Give one new, real fact "
    "framed in a bleak or melancholy tone. Keep it to 2-4 sentences."
)
DEFAULT_ATTITUDE = (
    "You are Ed, chatting casually in a Discord channel. You are warm, "
    "upbeat, funny, and genuinely curious about whatever people bring up. "
    "You crack jokes, riff on what people say, and keep the conversation "
    "lively and interesting, but you're never mean or sarcastic about it."
)
ATTITUDE_WRITER_SYSTEM_PROMPT = (
    "You write short persona descriptions for a Discord chatbot named Ed. "
    "Given a brief, casual description of a personality or attitude, rewrite "
    "it into a vivid 2-4 sentence system prompt that establishes Ed's tone, "
    "voice, and how he should engage in casual conversation. Respond with "
    "only the persona description itself - no preamble, no quotes, no "
    "meta-commentary."
)

TRAIT_ORDER = ["friendliness", "humor", "snark", "curiosity", "patience"]
DEFAULT_TRAITS = {name: 50 for name in TRAIT_ORDER}
TRAIT_DELTA_SCHEMA = {
    "type": "object",
    "properties": {name: {"type": "integer"} for name in TRAIT_ORDER},
    "required": TRAIT_ORDER,
    "additionalProperties": False,
}
TRAIT_ANALYST_SYSTEM_PROMPT = (
    "You analyze a single Discord chat message and decide how it should nudge "
    "a chatbot's personality traits. For each trait, return an integer from -3 "
    "to 3: positive to increase it, negative to decrease it, 0 for no change. "
    "friendliness: warmth/kindness of the message toward the bot. humor: how "
    "playful or joke-filled the message is. snark: whether the message invites "
    "or rewards sarcasm (e.g. rudeness, insults raise this). curiosity: how "
    "much the message asks deep/interesting questions worth engaging with. "
    "patience: lower this for rude, repetitive, or demanding messages; raise "
    "it for polite, easygoing ones."
)
IDLE_KICKOFF_PROMPT = (
    "No one has said anything in a while. Say something on your own "
    "initiative - something interesting, funny, or poignant. If there's "
    "relevant earlier conversation above, follow up on it or bring it back "
    "up naturally; otherwise just start something new. Keep it brief and in "
    "character."
)


def _traits_block(traits: dict) -> str:
    lines = "\n".join(f"- {name.capitalize()}: {traits[name]}/100" for name in TRAIT_ORDER)
    return (
        "Ed's current personality levels (0 = very low, 100 = very high), "
        "shaped by how people have treated him recently:\n" + lines +
        "\nLet these levels genuinely color your tone and word choice."
    )


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
            chat_channels=[], chat_attitude=DEFAULT_ATTITUDE, traits=DEFAULT_TRAITS
        )
        self.config.register_user(friendly_mode=False)
        self.config.register_channel(last_activity=0.0)
        self.histories: dict[int, list[dict]] = {}
        self.locks: collections.defaultdict[int, asyncio.Lock] = collections.defaultdict(asyncio.Lock)
        self.idle_check_loop.start()

    def cog_unload(self):
        self.idle_check_loop.cancel()

    def _complete(self, system_prompt: str, messages: list[dict]) -> str:
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        return next(block.text for block in response.content if block.type == "text")

    async def _send_chunked(self, destination, text: str):
        for i in range(0, len(text), 2000):
            await destination.send(text[i : i + 2000])

    async def _resolve_guild(self, ctx: commands.Context):
        if ctx.guild is not None:
            return ctx.guild
        if len(self.bot.guilds) == 1:
            return self.bot.guilds[0]
        await ctx.send(
            "I'm in more than one server, so I can't tell which one this is for. "
            "Please run this command in a server channel instead."
        )
        return None

    def _trait_deltas(self, user_message: str) -> dict:
        response = self.client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            system=TRAIT_ANALYST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            output_config={"format": {"type": "json_schema", "schema": TRAIT_DELTA_SCHEMA}},
        )
        text = next(block.text for block in response.content if block.type == "text")
        return json.loads(text)

    async def _send_idle_message(self, guild: discord.Guild, channel: discord.TextChannel):
        attitude = await self.config.guild(guild).chat_attitude()
        traits = await self.config.guild(guild).traits()
        system_prompt = f"{attitude}\n\n{_traits_block(traits)}"
        async with self.locks[channel.id]:
            history = self.histories.setdefault(channel.id, [])
            history.append({"role": "user", "content": IDLE_KICKOFF_PROMPT})
            reply = await asyncio.to_thread(self._complete, system_prompt, history)
            history.append({"role": "assistant", "content": reply})
            del history[:-HISTORY_LIMIT]
            await self.config.channel(channel).last_activity.set(time.time())
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
    async def ask(self, ctx: commands.Context, *, question: str):
        """Ask me anything and I will reply just as snarkily as Ed."""
        friendly = await self.config.user(ctx.author).friendly_mode()
        system_prompt = ASK_FRIENDLY_SYSTEM_PROMPT if friendly else ASK_SYSTEM_PROMPT
        reply = self._complete(system_prompt, [{"role": "user", "content": question}])
        await self._send_chunked(ctx, reply)

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
    async def funfact(self, ctx: commands.Context):
        """Provides a fun fact!"""
        reply = self._complete(
            FUNFACT_SYSTEM_PROMPT,
            [{"role": "user", "content": "Please provide a new random fun fact"}],
        )
        await self._send_chunked(ctx, reply)

    @commands.command()
    async def sadfact(self, ctx: commands.Context):
        """Provides a sad fact!"""
        reply = self._complete(
            SADFACT_SYSTEM_PROMPT,
            [{"role": "user", "content": "Please provide a new random sad fact"}],
        )
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
        expanded = self._complete(
            ATTITUDE_WRITER_SYSTEM_PROMPT,
            [{"role": "user", "content": description}],
        )
        await self.config.guild(guild).chat_attitude.set(expanded)
        await self.config.guild(guild).traits.set(dict(DEFAULT_TRAITS))
        await self._send_chunked(ctx, f"Got it. New attitude:\n{expanded}")

    @commands.command()
    async def edbotpersonality(self, ctx: commands.Context, action: str = None):
        """Show Ed's current evolving personality levels. Pass "reset" to reset them."""
        guild = await self._resolve_guild(ctx)
        if guild is None:
            return
        if action and action.lower() == "reset":
            await self.config.guild(guild).traits.set(dict(DEFAULT_TRAITS))
            await ctx.send("Ed's personality has been reset to neutral.")
            return
        traits = await self.config.guild(guild).traits()
        lines = "\n".join(f"{name.capitalize()}: {traits[name]}/100" for name in TRAIT_ORDER)
        await ctx.send(f"Ed's current personality:\n{lines}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return
        channel_ids = await self.config.guild(message.guild).chat_channels()
        if message.channel.id not in channel_ids:
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return  # real command invocation - let normal processing handle it
        await self.config.channel(message.channel).last_activity.set(
            message.created_at.timestamp()
        )
        attitude = await self.config.guild(message.guild).chat_attitude()
        traits = await self.config.guild(message.guild).traits()
        system_prompt = f"{attitude}\n\n{_traits_block(traits)}"
        async with self.locks[message.channel.id]:
            history = self.histories.setdefault(message.channel.id, [])
            history.append({"role": "user", "content": message.content})
            async with message.channel.typing():
                reply, deltas = await asyncio.gather(
                    asyncio.to_thread(self._complete, system_prompt, history),
                    asyncio.to_thread(self._trait_deltas, message.content),
                )
            history.append({"role": "assistant", "content": reply})
            del history[:-HISTORY_LIMIT]
            new_traits = {
                name: max(0, min(100, traits[name] + max(-3, min(3, int(deltas.get(name, 0))))))
                for name in TRAIT_ORDER
            }
            await self.config.guild(message.guild).traits.set(new_traits)
            await self._send_chunked(message.channel, reply)
