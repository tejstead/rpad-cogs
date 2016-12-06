import http.client
import urllib.parse
import json
import re

import os

import traceback

import time
import threading
import asyncio
import discord
import random

from enum import Enum

from discord.ext import commands
from .utils.chat_formatting import *
from .utils.dataIO import fileIO
from .utils import checks
from .utils.twitter_stream import *
from __main__ import user_allowed, send_cmd_help

from collections import defaultdict

from .utils.cog_settings import *


class TrUtils:
    def __init__(self, bot):
        self.bot = bot
        self.settings = TrUtilsSettings("trutils")
        self.colors = [
           discord.Color.blue(),
           discord.Color.dark_blue(),
           discord.Color.dark_gold(),
           discord.Color.dark_green(),
           discord.Color.dark_grey(),
           discord.Color.dark_magenta(),
           discord.Color.dark_orange(),
           discord.Color.dark_purple(),
           discord.Color.dark_red(),
           discord.Color.dark_teal(),
           discord.Color.darker_grey(),
           discord.Color.default(),
           discord.Color.gold(),
           discord.Color.green(),
           discord.Color.light_grey(),
           discord.Color.lighter_grey(),
           discord.Color.magenta(),
           discord.Color.orange(),
           discord.Color.purple(),
           discord.Color.red(),
           discord.Color.teal(),
       ]

    def registerTasks(self, event_loop):
        print("registering tasks")
        self.rainbow_task = event_loop.create_task(self.refresh_rainbow())

    def __unload(self):
        print("unloading trutils")
        self.rainbow_task.cancel()

    async def refresh_rainbow(self):
        print("rainbow refresher")
        while "TrUtils" in self.bot.cogs:
            try:
                await asyncio.sleep(10)
            except Exception as e:
                print("refresh rainbow loop caught exception " + str(e))
                raise e

            try:
                await self.doRefreshRainbow()
            except Exception as e:
                traceback.print_exc()
                print("caught exception while refreshing rainbow " + str(e))

        print("done refresh_rainbow")

    async def doRefreshRainbow(self):
        servers = self.settings.servers()
        for server_id, server_data in servers.items():
            server = self._get_server_from_id(server_id)
            rainbow_ids = self.settings.rainbow(server_id)
            for role_id in rainbow_ids:
                role = self._get_role_from_id(server, role_id)
                color = random.choice(self.colors)
                try:
                    await self.bot.edit_role(server, role, color=color)
                except Exception as e:
                    traceback.print_exc()
                    print("caught exception while updating role, disabling: " + str(e))
                    self.settings.clearRainbow(server_id, role_id)

    async def on_ready(self):
        """ready"""
        print("started trutils")

    async def check_for_nickname_change(self, before, after):
        try:
            server = after.server
            saved_nick = self.settings.getNickname(server.id, after.id)
            if saved_nick is None:
                return

            if not len(saved_nick):
                saved_nick = None

            if before.nick != after.nick:
                if after.nick != saved_nick:
                    print("caught bad nickname change {} {}".format(after.nick, saved_nick))
                    await self.bot.change_nickname(after, saved_nick)
        except Exception as e:
            traceback.print_exc()
            print('failed to check for nickname change' + str(e))

    @commands.command(name="dontchangemyname", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def dontchangemyname(self, ctx, nickname):
        self.settings.setNickname(ctx.message.server.id, ctx.message.author.id, nickname)
        await self.bot.say('`done`')

    @commands.command(name="cleardontchangemyname", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def cleardontchangemyname(self, ctx):
        self.settings.clearNickname(ctx.message.server.id, ctx.message.author.id)
        await self.bot.say('`done`')

    @commands.command(name="rainbow", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def rainbow(self, ctx, role_name):
        role = self._get_role(ctx.message.server.roles, role_name)
        self.settings.setRainbow(ctx.message.server.id, role.id)
        await self.bot.say('`done`')

    @commands.command(name="clearrainbow", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def clearrainbow(self, ctx, role_name):
        role = self._get_role(ctx.message.server.roles, role_name)
        self.settings.clearRainbow(ctx.message.server.id, role.id)
        await self.bot.say('`done`')

    def _get_role(self, roles, role_string):
        if role_string.lower() == "everyone":
            role_string = "@everyone"

        role = discord.utils.find(
            lambda r: r.name.lower() == role_string.lower(), roles)

        if role is None:
            raise RoleNotFound(roles[0].server, role_string)

        return role

    def _get_role_from_id(self, server, roleid):
        try:
            roles = server.roles
        except AttributeError:
            server = self._get_server_from_id(server)
            try:
                roles = server.roles
            except AttributeError:
                raise ValueError()

        role = discord.utils.get(roles, id=roleid)
        if role is None:
            raise RoleNotFound(server, roleid)
        return role

    def _get_server_from_id(self, serverid):
        return discord.utils.get(self.bot.servers, id=serverid)

def setup(bot):
    print('trutils bot setup')
    n = TrUtils(bot)
    n.registerTasks(asyncio.get_event_loop())
    bot.add_listener(n.check_for_nickname_change, "on_member_update")
    bot.add_cog(n)
    print('done adding trutils bot')


class TrUtilsSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'servers': {},
        }
        return config

    def servers(self):
        return self.bot_settings['servers']

    def getServer(self, server_id):
        servers = self.servers()
        if server_id not in servers:
            servers[server_id] = {}
        return servers[server_id]

    def setNickname(self, server_id, user_id, nickname):
        server = self.getServer(server_id)
        server[user_id] = nickname
        self.save_settings()

    def getNickname(self, server_id, user_id):
        server = self.getServer(server_id)
        return server.get(user_id)

    def clearNickname(self, server_id, user_id):
        server = self.getServer(server_id)
        if user_id in server:
            server.pop(user_id)
        self.save_settings()

    def rainbow(self, server_id):
        server = self.getServer(server_id)
        if 'rainbow' not in server:
            server['rainbow'] = []
        return server['rainbow']

    def setRainbow(self, server_id, role_id):
        rainbow = self.rainbow(server_id)
        if role_id not in rainbow:
            rainbow.append(role_id)
            self.save_settings()

    def clearRainbow(self, server_id, role_id):
        rainbow = self.rainbow(server_id)
        if role_id in rainbow:
            rainbow.remove(role_id)
            self.save_settings()


