import configparser
import json
from pathlib import Path

import aiohttp
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
