from collections import defaultdict
import os
import re

import discord
from discord.ext import commands
from googleapiclient.discovery import build

from __main__ import user_allowed, send_cmd_help

from .rpadutils import *
from .utils import checks
from .utils.cog_settings import *
from .utils.dataIO import dataIO


class Translate:
    """Translation utilities."""

    def __init__(self, bot):
        self.bot = bot
        self.settings = TranslateSettings("translate")

        self.service = None
        self.trySetupService()

    def trySetupService(self):
        api_key = self.settings.getKey()
        if api_key:
            self.service = build('translate', 'v2', developerKey=api_key)

    @commands.group(pass_context=True)
    async def translate(self, context):
        """Translation utilities."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)


    @commands.command(pass_context=True, aliases=['jaus', 'jpen', 'jpus'])
    async def jaen(self, ctx, *, query):
        """Translates from Japanese to English"""
        if not self.service:
            await self.bot.say(inline('Set up an API key first!'))
            return

        result = self.service.translations().list(source='ja', target='en', format='text', q=query).execute()
        translation = result.get('translations')[0].get('translatedText')

        em = discord.Embed(description='**Original**\n`{}`\n\n**Translation**\n`{}`'.format(query, translation))
        await self.bot.say(embed=em)

    @translate.command(pass_context=True)
    @checks.is_owner()
    async def setkey(self, ctx, api_key):
        """Sets the google api key."""
        self.settings.setKey(api_key)
        await self.bot.say("done")


def setup(bot):
    n = Translate(bot)
    bot.add_cog(n)


class TranslateSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'google_api_key' : ''
        }
        return config

    def getKey(self):
        return self.bot_settings.get('google_api_key')

    def setKey(self, api_key):
        self.bot_settings['google_api_key'] = api_key
        self.save_settings()
