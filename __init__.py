from .edbot import EdBot


async def setup(bot):
    await bot.add_cog(EdBot(bot))
