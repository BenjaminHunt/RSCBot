from discord.ext import commands

class AnnoyJK:

    JK_ID = 226869393626234881

    def __init__(self, bot):
        self.bot = bot

    async def on_message(self, message):
        if message.author.id == 226869393626234881:
            await self.bot.add_reaction(message, '👍')

def setup(bot):
    n = AnnoyJK(bot)
    bot.add_listener(n.on_message, "on_message")
    bot.add_cog(n)