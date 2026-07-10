import configparser
from pathlib import Path

import anthropic
from redbot.core import commands

MODEL = "claude-sonnet-5"

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


def _load_api_key(conf_path: Path) -> str:
    parser = configparser.ConfigParser()
    parser.read_string("[DEFAULT]\n" + conf_path.read_text())
    return parser["DEFAULT"]["api_key"].strip('"')


class EdBot(commands.Cog):
    """Snarky Claude-powered bot."""

    def __init__(self, bot):
        self.bot = bot
        api_key = _load_api_key(Path(__file__).parent / "edbot.conf")
        self.client = anthropic.Anthropic(api_key=api_key)

    async def _reply(self, ctx: commands.Context, system_prompt: str, user_content: str):
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        text = next(block.text for block in response.content if block.type == "text")
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
