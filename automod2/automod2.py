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

from .utils import checks
from .utils.cog_settings import *
from .utils.dataIO import fileIO
from .utils.settings import Settings


def mod_or_perms(ctx, **perms):
    server = ctx.message.server
    mod_role = settings.get_server_mod(server).lower()
    admin_role = settings.get_server_admin(server).lower()
    return checks.role_or_permissions(ctx, lambda r: r.name.lower() in (mod_role, admin_role), **perms)

class CtxWrapper:
    def __init__(self, msg):
        self.message = msg


class AutoMod2:
    def __init__(self, bot):
        self.bot = bot

        self.settings = AutoMod2Settings("automod2")

    @commands.group(pass_context=True, no_pm=True)
    async def automod2(self, context):
        """AutoMod2 tools."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @automod2.command(name="addpattern", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addPattern(self, ctx, name, include_pattern, exclude_pattern=''):
        re.compile(include_pattern)
        re.compile(exclude_pattern)
        self.settings.addPattern(ctx, name, include_pattern, exclude_pattern)
        await self.bot.say(inline('Added pattern'))

    @automod2.command(name="rmpattern", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmPattern(self, ctx, name):
        self.settings.rmPattern(ctx, name)
        await self.bot.say(inline('Removed pattern'))

    @automod2.command(name="addwhitelist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addWhitelist(self, ctx, name):
        self.settings.addWhitelist(ctx, name)
        await self.bot.say(inline('Added whitelist config for: ' + name))

    @automod2.command(name="rmwhitelist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmWhitelist(self, ctx, name):
        self.settings.rmWhitelist(ctx, name)
        await self.bot.say(inline('Removed whitelist config for: ' + name))

    @automod2.command(name="addblacklist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addBlacklist(self, ctx, name):
        self.settings.addBlacklist(ctx, name)
        await self.bot.say(inline('Added blacklist config for: ' + name))

    @automod2.command(name="rmblacklist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmBlacklist(self, ctx, name):
        self.settings.rmBlacklist(ctx, name)
        await self.bot.say(inline('Removed blacklist config for: ' + name))

    @automod2.command(name="listrules", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def listRules(self, ctx):
        whitelists, blacklists = self.settings.getRulesForChannel(ctx)

        output = 'AutoMod configs for this channel\n\n'
        output += 'Whitelists:\n'
        for value in whitelists:
            output += '\t"{}" -> includes=[ {} ] excludes=[ {} ]\n'.format(
               value['name'], value['include_pattern'], value['exclude_pattern'])
        output += 'Blacklists:\n'
        for value in blacklists:
            output += '\t"{}" -> includes=[ {} ] excludes=[ {} ]\n'.format(
               value['name'], value['include_pattern'], value['exclude_pattern'])

        await self.bot.say(box(output))

    @automod2.command(name="listpatterns", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def listPatterns(self, ctx):
        patterns = self.settings.getPatterns(ctx)

        output = 'AutoMod patterns for this server\n'
        for name, value in patterns.items():
            output += '\t"{}" -> includes=[ {} ] excludes=[ {} ]\n'.format(
               value['name'], value['include_pattern'], value['exclude_pattern'])

        await self.bot.say(box(output))

    async def mod_message_edit(self, before, after):
        await self.mod_message(after)

    async def mod_message(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return

        ctx = CtxWrapper(message)
        if mod_or_perms(ctx, kick_members=True):
            return

        whitelists, blacklists = self.settings.getRulesForChannel(ctx)

        msg_template = box('Your message in {} was deleted for violating the following policy: {}\n'
                           'Message content: {}')

        msg_content = message.clean_content
        for value in blacklists:
            name = value['name']
            include_pattern = value['include_pattern']
            exclude_pattern = value['exclude_pattern']

            if not matchesIncludeExclude(include_pattern, exclude_pattern, msg_content):
                continue

            msg = msg_template.format(message.channel.name, name, msg_content)
            await self.deleteAndReport(message, msg)

        if len(whitelists):
            failed_whitelists = list()
            for value in whitelists:
                name = value['name']
                include_pattern = value['include_pattern']
                exclude_pattern = value['exclude_pattern']

                if matchesIncludeExclude(include_pattern, exclude_pattern, msg_content):
                    return
                failed_whitelists.append(name)

            msg = msg_template.format(message.channel.name, ','.join(failed_whitelists), msg_content)
            await self.deleteAndReport(message, msg)

    async def deleteAndReport(self, delete_msg, outgoing_msg):
        try:
            await self.bot.delete_message(delete_msg)
            await self.bot.send_message(delete_msg.author, outgoing_msg)
        except Exception as e:
            print('Failure while deleting message from {}, tried to send : {}'.format(delete_msg.author.name, outgoing_msg))
            print(str(e))

def matchesPattern(pattern, txt):
    if not len(pattern):
        return False

    try:
        if pattern[0] == pattern[-1] == ':':
            print(pattern[1:-1])
            check_method = globals().get(pattern[1:-1])
            if check_method:
                return check_method(txt)
    except:
        print('Failed method pattern match:', pattern, txt)
        return False

    p = re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return p.match(txt)

def starts_with_code(txt):
    txt = txt.replace(' ', '')
    if len(txt) < 8:
        return False
    return pad_checkdigit(txt[0:8])

def pad_checkdigit(n):
    n = str(n)
    checkdigit = int(n[7])
    sum = 7
    for idx in range(0, 7):
        sum += int(n[idx])
    calcdigit = sum % 10
    return checkdigit == calcdigit

def matchesIncludeExclude(include_pattern, exclude_pattern, txt):
    if matchesPattern(include_pattern, txt):
        return not matchesPattern(exclude_pattern, txt)
    return False


def setup(bot):
    print('automod2 bot setup')
    n = AutoMod2(bot)
    bot.add_listener(n.mod_message, "on_message")
    bot.add_listener(n.mod_message_edit, "on_message_edit")
    bot.add_cog(n)
    print('done adding automod2 bot')


class AutoMod2Settings(CogSettings):
    def make_default_settings(self):
        config = {
          'configs' : {}
        }
        return config

    def serverConfigs(self):
        return self.bot_settings['configs']

    def getServer(self, ctx):
        configs = self.serverConfigs()
        server_id = ctx.message.server.id
        if server_id not in configs:
            configs[server_id] = {
              'patterns': {},
              'channels': {},
            }
        return configs[server_id]

    def getChannels(self, ctx):
        server = self.getServer(ctx)
        if 'channels' not in server:
            server['channels'] = {}
        return server['channels']

    def getChannel(self, ctx):
        channels = self.getChannels(ctx)

        channel_id = ctx.message.channel.id
        if channel_id not in channels:
            channels[channel_id] = {
                'whitelist': [],
                'blacklist': [],
            }

        return channels[channel_id]

    def getRulesForChannel(self, ctx):
        patterns = self.getPatterns(ctx)
        channel = self.getChannel(ctx)

        whitelist = [patterns[name] for name in channel['whitelist']]
        blacklist = [patterns[name] for name in channel['blacklist']]
        return whitelist, blacklist

    def getPatterns(self, ctx):
        server = self.getServer(ctx)
        if 'patterns' not in server:
            server['patterns'] = {}
        return server['patterns']

    def addPattern(self, ctx, name, include_pattern, exclude_pattern):
        patterns = self.getPatterns(ctx)
        patterns[name] = {
            'name': name,
            'include_pattern': include_pattern,
            'exclude_pattern': exclude_pattern,
        }
        self.save_settings()

    def checkPatternUsed(self, ctx, name):
        server = self.getServer(ctx)
        print(server)
        for channel_id, channel_config in server['channels'].items():
            print(channel_config)
            if name in channel_config['whitelist']:
                return True
            if name in channel_config['blacklist']:
                return True
        return False

    def rmPattern(self, ctx, name):
        if self.checkPatternUsed(ctx, name):
            raise ValueError("that pattern is in use")
        self.getPatterns(ctx).pop(name)
        self.save_settings()

    def addRule(self, ctx, name, list_type):
        patterns = self.getPatterns(ctx)
        if name not in patterns:
            raise ValueError("couldn't find rule name")
        self.getChannel(ctx)[list_type].append(name)
        self.save_settings()

    def rmRule(self, ctx, name, list_type):
        self.getChannel(ctx)[list_type].remove(name)
        self.save_settings()

    def addWhitelist(self, ctx, name):
        self.addRule(ctx, name, 'whitelist')

    def rmWhitelist(self, ctx, name):
        self.rmRule(ctx, name, 'whitelist')

    def addBlacklist(self, ctx, name):
        self.addRule(ctx, name, 'blacklist')

    def rmBlacklist(self, ctx, name):
        self.rmRule(ctx, name, 'blacklist')


