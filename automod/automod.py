import discord
from .utils import checks
from discord.ext import commands
from .utils.dataIO import fileIO
from .utils.settings import Settings
from __main__ import settings
from __main__ import send_cmd_help
from time import time
import os

from collections import deque
from collections import defaultdict
import copy

import re

from .utils.cog_settings import *

def mod_or_perms(ctx, **perms):
    server = ctx.message.server
    mod_role = settings.get_server_mod(server).lower()
    admin_role = settings.get_server_admin(server).lower()
    return checks.role_or_permissions(ctx, lambda r: r.name.lower() in (mod_role,admin_role), **perms)


class CtxWrapper:
    def __init__(self, msg):
        self.message = msg


class AutoMod:
    def __init__(self, bot):
        self.bot = bot
        
        self.settings = AutoModSettings("automod")

    @commands.group(pass_context=True, no_pm=True)
    async def automod(self, context):
        """AutoMod tools."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @automod.command(name="addwhitelist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addWhitelist(self, ctx, name, value):
        try:
            re.compile(value) 
            self.settings.addWhitelist(ctx, name, value)
            await self.bot.say(inline('Added whitelist config for "' + name + '" with value: ' + value))
        except Exception as e:
            await self.bot.say(inline('Error! Maybe regex was invalid: ' + value))
            print(str(e))
            
            
    @automod.command(name="rmwhitelist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmWhitelist(self, ctx, name):
        self.settings.rmWhitelist(ctx, name)
        await self.bot.say(inline('Removed whitelist config for "' + name + '"'))

    @automod.command(name="addblacklist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addBlacklist(self, ctx, name, value):
        try:
            re.compile(value)
            self.settings.addBlacklist(ctx, name, value)
            await self.bot.say(inline('Added blacklist config for "' + name + '" with value: ' + value))
        except Exception as e:
            await self.bot.say(inline('Error! Maybe regex was invalid: ' + value))
            print(str(e))
            
    @automod.command(name="rmblacklist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmBlacklist(self, ctx, name):
        self.settings.rmBlacklist(ctx, name)
        await self.bot.say(inline('Removed blacklist config for "' + name + '"'))

    @automod.command(name="addreplacement", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addReplacement(self, ctx, name, search_value, replacement_value):
        try:
            re.compile(search_value)
            self.settings.addReplacement(ctx, name, search_value, replacement_value)
            await self.bot.say(inline('Added replace config for "' + name + '" with value: {} -> {}'.format(search_value, replacement_value)))
        except Exception as e:
            await self.bot.say(inline('Error! Maybe regex was invalid: ' + value))
            print(str(e))
            
    @automod.command(name="rmreplacement", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmReplacement(self, ctx, name):
        self.settings.rmReplacement(ctx, name)
        await self.bot.say(inline('Removed replacement config for "' + name + '"'))
            
    @automod.command(name="list", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def list(self, ctx):
        configs = self.settings.getChannel(ctx)
        output = 'AutoMod configs for this channel\n\n'
        output += 'Whitelists:\n'
        for name, value in configs['whitelist'].items():
            output += '\t"{}" -> {}\n'.format(name, value)    
        output += 'Blacklists:\n'
        for name, value in configs['blacklist'].items():
            output += '\t"{}" -> {}\n'.format(name, value)
        output += 'Replacements:\n'
        for name, values in configs['replacement'].items():
            output += '\t"{}" -> ({} -> )\n'.format(name, values[0], values[1])
        
        await self.bot.say(box(output))

    async def mod_message_edit(self, before, after):
        await self.mod_message(after)
    
    async def mod_message(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return
        
        ctx = CtxWrapper(message)        
        is_mod = mod_or_perms(ctx, kick_members=True)
        if is_mod:
            return

        configs = self.settings.getChannel(ctx)
        whitelists = configs['whitelist']
        blacklists = configs['blacklist']
        
        msg_template = box('Your message in {} was deleted for violating the following policy: {}\n'
                           'Message content: {}')
        
        for name, value in blacklists.items():
            p = re.compile(value, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if p.match(message.clean_content):
                msg = msg_template.format(message.channel.name, name, message.clean_content)
                try:
                    await self.bot.delete_message(message)
                    await self.bot.send_message(message.author, msg)
                except Exception as e:
                    print('Failure while deleting message from {}, tried to send : {}'.format(message.author.name, msg))
                    print(str(e))
                return
        
        if len(whitelists):
            for name, value in whitelists.items():
                p = re.compile(value, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                if p.match(message.clean_content):
                    return
                msg = msg_template.format(message.channel.name, name, message.clean_content)
                try:
                    await self.bot.delete_message(message)
                    await self.bot.send_message(message.author, msg)
                except Exception as e:
                    print('Failure while deleting message from {}, tried to send : {}'.format(message.author.name, msg))
                    print(str(e))
                return
        
        
        replacements = configs['replacement']
        
        msg_template = box('Your message in {} was automatically modified because it matched the following policy: {}\n'
                           'Original content: {}\n'
                           'Adjusted content: {}\n')
        
        if len(replacements):
            for name, value in replacements.items():
                search_value = value[0]
                replacement_value = value[1]
                
                p = re.compile(search_value, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                (adjusted_msg, match_count) = p.subn(replacement_value, message.clean_content)
                
                if adjusted_msg != message.clean_content:
                    msg = msg_template.format(message.channel.name, name, message.clean_content, adjusted_msg)
                    
                    try:
                        await self.bot.edit_message(message, adjusted_msg)
                        await self.bot.send_message(message.author, msg)
                    except Exception as e:
                        print('Failure while editing message from {}, tried to send : {}'.format(message.author.name, msg))
                        print(str(e))
                    return
        

def setup(bot):
    print('automod bot setup')
    n = AutoMod(bot)
    bot.add_listener(n.mod_message, "on_message")
    bot.add_listener(n.mod_message_edit, "on_message_edit")
    bot.add_cog(n)
    print('done adding automod bot')


class AutoModSettings(CogSettings):
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
            configs[server_id] = {}
        return configs[server_id]

    def getChannel(self, ctx):
        server = self.getServer(ctx)
        
        channel_id = ctx.message.channel.id
        if channel_id not in server:
            server[channel_id] = {}
        
        channel = server[channel_id]
        if 'whitelist' not in channel:
            channel['whitelist'] = {}
        if 'blacklist' not in channel:
            channel['blacklist'] = {}
        if 'replacement' not in channel:
            channel['replacement'] = {}
            
        return channel

    def addWhitelist(self, ctx, name, value):
        channel = self.getChannel(ctx)
        channel['whitelist'][name] = value
        self.save_settings()

    def rmWhitelist(self, ctx, name):
        channel = self.getChannel(ctx)
        channel['whitelist'].pop(name)
        self.save_settings()

    def addBlacklist(self, ctx, name, value):
        channel = self.getChannel(ctx)
        channel['blacklist'][name] = value
        self.save_settings()

    def rmBlacklist(self, ctx, name):
        channel = self.getChannel(ctx)
        channel['blacklist'].pop(name)
        self.save_settings()

    def addReplacement(self, ctx, name, search_value, replacement_value):
        channel = self.getChannel(ctx)
        channel['replacement'][name] = (search_value, replacement_value)
        self.save_settings()

    def rmReplacement(self, ctx, name):
        channel = self.getChannel(ctx)
        channel['replacement'].pop(name)
        self.save_settings()

