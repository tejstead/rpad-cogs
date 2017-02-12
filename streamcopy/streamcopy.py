from collections import defaultdict
from collections import deque
import copy
import os
import random
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

    @streamcopy.command(name="refresh")
    async def refresh(self):
        other_stream = await self.do_refresh()
        if other_stream:
            await self.bot.say(inline('Updated stream'))
        else:
            await self.bot.say(inline('Could not find a streamer'))

    async def check_stream(self, before, after):
        try:
            tracked_users = self.settings.users()
            if before.id not in tracked_users:
                return

            if self.is_playing(after):
                await self.copy_playing(after.game)
                return

            await self.do_refresh()
        except ex:
            print("Stream checking failed", ex)

    async def do_refresh(self):
        other_stream = self.find_stream()
        if other_stream:
            await self.copy_playing(other_stream)
        else:
            await self.bot.change_presence(game=None)
        return other_stream

    def find_stream(self):
        user_ids = self.settings.users().keys()
        members = {x.id: x for x in self.bot.get_all_members() if x.id in user_ids and self.is_playing(x)}
        games = [x.game for x in members.values()]
        random.shuffle(games)
        return games[0] if len(games) else None

    def is_playing(self, member : discord.Member):
        return member and member.game and member.game.type == 1 and member.game.url

    async def copy_playing(self, game : discord.Game):
        new_game = discord.Game(name=game.name, url=game.url, type=game.type)
        await self.bot.change_presence(game=new_game)



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
