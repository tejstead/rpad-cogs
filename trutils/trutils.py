import asyncio
from collections import defaultdict
from enum import Enum
import http.client
import json
import os
import random
import re
import threading
import time
import traceback
import urllib.parse

import discord
from discord.ext import commands

from __main__ import user_allowed, send_cmd_help

from .rpadutils import *
from .utils import checks
from .utils.chat_formatting import *
from .utils.cog_settings import *
from .utils.dataIO import fileIO
from .utils.twitter_stream import *


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
                role = _get_role_from_id(self.bot, server, role_id)
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
        role = _get_role(ctx.message.server.roles, role_name)
        self.settings.setRainbow(ctx.message.server.id, role.id)
        await self.bot.say('`done`')

    @commands.command(name="clearrainbow", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def clearrainbow(self, ctx, role_name):
        role = _get_role(ctx.message.server.roles, role_name)
        self.settings.clearRainbow(ctx.message.server.id, role.id)
        await self.bot.say('`done`')

    @commands.command()
    async def userhelp(self):
        """Shows a summary of the useful user features"""
        about = (
            "Check back later"
        )
        await self.bot.whisper(inline(about))

    @commands.command()
    async def modhelp(self):
        """Shows a summary of the useful moderator features"""
        about = (
            "Check back later"
        )
        await self.bot.whisper(inline(about))

    @commands.command()
    async def credits(self):
        """Shows info about this bot"""
        author_repo = "https://github.com/Twentysix26"
        red_repo = author_repo + "/Red-DiscordBot"
        rpad_invite = "https://discord.gg/pad"

        about = (
            "This is an instance of [the Red Discord bot]({}), "
            "use the 'info' command for more info. "
            "The various PAD related cogs were created by tactical_retreat. "
            "This bot was created for the [PAD subreddit discord]({}) but "
            "is available for other servers on request."
            "".format(red_repo, rpad_invite))

        baby_miru_url = "http://www.pixiv.net/member_illust.php?illust_id=57613867&mode=medium"
        baby_miru_author = "BOW @ Pixiv"
        cute_miru_url = "https://www.dropbox.com/s/0wlfx3g4mk8c8bg/Screenshot%202016-12-03%2018.39.37.png?dl=0"
        cute_miru_author = "Pancaaake18 @ the MantasticPAD server on discord"
        avatar = (
            "Bot avatars supplied by:\n"
            "\t[Baby Miru]({}): {}\n"
            "\t[Cute Miru]({}): {}"
            "".format(baby_miru_url, baby_miru_author,
                      cute_miru_url, cute_miru_author))

        using = (
             "You can use `^help` to get a full list of commands.\n"
             "Use `^userhelp` to get a summary of useful user features.\n"
             "Use `^modhelp` to get info on moderator-only features."
        )

        embed = discord.Embed()
        embed.add_field(name="Instance owned by", value='tactical_retreat')
        embed.add_field(name="About the bot", value=about, inline=False)
        embed.add_field(name="Using the bot", value=using, inline=False)
        embed.add_field(name="Avatar credits", value=avatar, inline=False)
        embed.set_thumbnail(url=self.bot.user.avatar_url)

        try:
            await self.bot.say(embed=embed)
        except discord.HTTPException:
            await self.bot.say("I need the `Embed links` permission "
                               "to send this")

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def supersecretdebug(self, ctx, *, code):
        await self.superdebug(ctx, code=code)
        await self.bot.delete_message(ctx.message)

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def superdebug(self, ctx, *, code):
        """Evaluates code"""
        def check(m):
            if m.content.strip().lower() == "more":
                return True

        author = ctx.message.author
        channel = ctx.message.channel

        code = code.strip('` ')
        result = None

        global_vars = globals().copy()
        global_vars['bot'] = self.bot
        global_vars['ctx'] = ctx
        global_vars['message'] = ctx.message
        global_vars['author'] = ctx.message.author
        global_vars['channel'] = ctx.message.channel
        global_vars['server'] = ctx.message.server

        local_vars = locals().copy()
        local_vars['to_await'] = list()

        try:
            eval(compile(code, '<string>', 'exec'), global_vars, local_vars)
            to_await = local_vars['to_await']
        except Exception as e:
            await self.bot.say(box('{}: {}'.format(type(e).__name__, str(e)),
                                   lang="py"))
            return

        for result in to_await:
            if asyncio.iscoroutine(result):
                result = await result

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


