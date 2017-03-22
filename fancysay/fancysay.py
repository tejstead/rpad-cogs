from collections import defaultdict
from collections import deque
import copy
import os
from time import time

import discord
from discord.ext import commands

from __main__ import send_cmd_help

from .utils import checks
from .utils.dataIO import fileIO


LOGS_PER_CHANNEL = 1000

class FancySay:
    def __init__(self, bot):
        self.bot = bot

    @commands.group(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_channels=True)
    async def fancysay(self, context):
        """Make the bot say fancy things (via embeds)."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @fancysay.command(pass_context=True, no_pm=True)
    async def emoji(self, ctx, *, text):
        """Speak the provided text as emojis, deleting the original request"""
        await self.bot.delete_message(ctx.message)
        new_msg = ""
        for char in text:
            if char.isalpha():
                new_msg += ':regional_indicator_{}: '.format(char.lower())
            elif char == ' ':
                new_msg += '   '
            elif char.isspace():
                new_msg += char

        if len(new_msg):
            await self.bot.say(new_msg)

    @fancysay.command(pass_context=True, no_pm=True)
    async def title_description_image_footer(self, ctx, title, description, image, footer):
        """[title] [description] [image_url] [footer_text]

        You must specify a title. You can omit any of description, image, or footer.
        To omit an item use empty quotes. For the text fields, wrap your text in quotes.
        The bot will automatically delete your 'say' command if it can

        e.g. say with all fields:
        fancysay title_description_image_footer "My title text" "Description text" "xyz.com/image.png" "source: xyz.com"

        e.g. say with only title and image:
        fancysay title_descirption_image_footer "My title" "" "xyz.com/image.png" ""
        """

        embed = discord.Embed()
        if len(title):
            embed.title = title
        if len(description):
            embed.description = description
        if len(image):
            embed.set_image(url=image)
        if len(footer):
            embed.set_footer(text=footer)

        try:
            await self.bot.say(embed=embed)
            await self.bot.delete_message(ctx.message)
        except Exception as error:
            print("failed to fancysay", error)

def setup(bot):
    n = FancySay(bot)
    bot.add_cog(n)
