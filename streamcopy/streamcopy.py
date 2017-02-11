from collections import defaultdict
from collections import deque
import copy
import os
import re
from time import time

import discord
from discord.ext import commands

from __main__ import send_cmd_help
from __main__ import settings

from .rpadutils import *
from .utils import checks
from .utils.cog_settings import *
from .utils.dataIO import fileIO
from .utils.settings import Settings


class StreamCopy:
    def __init__(self, bot):
        self.bot = bot
        self.settings = StreamCopySettings("streamcopy")
        self.current_user_id = None

    @commands.group(pass_context=True)
    @checks.is_owner()
    async def streamcopy(self, context):
        """streamcopy."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @streamcopy.command(name="adduser", pass_context=True)
    async def addUser(self, ctx, user : discord.User, priority : int):
        self.settings.addUser(user.id, priority)
        await self.bot.say(inline('Done'))

    @streamcopy.command(name="rmuser", pass_context=True)
    async def rmUser(self, ctx, user : discord.User):
        self.settings.rmUser(user.id)
        await self.bot.say(inline('Done'))

    @streamcopy.command(name="refresh", pass_context=True, no_pm=True)
    async def refresh(self, ctx):
        for user_id in self.settings.users().keys():
            member = ctx.message.server.get_member(user_id)
            if member and self.is_playing(member):
                game = member.game
                new_game = discord.Game(name=game.name, url=game.url, type=game.type)
                await self.bot.change_presence(game=new_game)
                await self.bot.say(inline('Updated stream'))
                return

        await self.bot.change_presence(game=None)
        await self.bot.say(inline('Could not find a streamer'))


    async def check_stream(self, before, after):
        try:
            tracked_users = self.settings.users()
            if before.id not in tracked_users:
                return

            if self.is_playing(after):
                game = after.game
                new_game = discord.Game(name=game.name, url=game.url, type=game.type)
                await self.bot.change_presence(game=new_game)
            elif self.is_playing(before):
                await self.bot.change_presence(game=None)
        except ex:
            print("Stream checking failed", ex)


    def is_playing(self, member : discord.Member):
        game = member.game
        return game and game.type == 1 and game.url


def setup(bot):
    print('streamcopy bot setup')
    n = StreamCopy(bot)
    bot.add_listener(n.check_stream, "on_member_update")
    bot.add_cog(n)
    print('done adding streamcopy bot')


class StreamCopySettings(CogSettings):
    def make_default_settings(self):
        config = {
          'users' : {}
        }
        return config

    def users(self):
        return self.bot_settings['users']

    def addUser(self, user_id, priority):
        users = self.users()
        users[user_id] = {'priority': priority}
        self.save_settings()

    def rmUser(self, user_id):
        users = self.users()
        if user_id in users:
            users.pop(user_id)
            self.save_settings()
