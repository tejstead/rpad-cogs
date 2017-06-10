"""
Lets you create patterns to match against messages and apply them as whitelists
or blacklists to a channel.

If a violation occurs, the message will be deleted and the user notified.
"""

from collections import defaultdict
from collections import deque
import copy
import os
import re
from time import time

import discord
from discord.ext import commands
import prettytable

from __main__ import send_cmd_help
from __main__ import settings
from .rpadutils import *

from .utils import checks
from .utils.cog_settings import *
from .utils.dataIO import fileIO
from .utils.settings import Settings

LOGS_PER_CHANNEL_USER = 5

def linked_img_count(message):
    return len(message.embeds) + len(message.attachments)

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
        self.channel_user_logs = defaultdict(lambda: deque(maxlen=LOGS_PER_CHANNEL_USER))

    @commands.group(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def automod2(self, context):
        """AutoMod2 tools.

        This cog works by creating named global patterns, and then applying them in
        specific channels as either whitelist or blacklist rules. This allows you
        to customize what text can be typed in a channel. Text from moderators is
        always ignored by this cog.

        Check out [p]listpatterns to see the current server-specific list of patterns.

        Each pattern has an 'include' component and an 'exclude' component. If text
        matches the include, then the rule matches. If it subsequently matches the
        exclude, then it does not match.

        Here's an example pattern:
        Rule Name                              Include regex        Exclude regex
        -----------------------------------------------------------------------------
        messages must start with a room code   ^\d{4}\s?\d{4}.*     .*test.*

        This pattern will match values like:
          12345678 foo fiz
          1234 5678 bar baz

        However, if the pattern contains 'test', it won't match:
          12345678 foo fiz test bar baz

        To add the pattern, you'd use the following command:
        [p]automod2 addpattern "messages must start with a room code" "^\d{4}\s?\d{4}.*" ".*test.*"

        Remember that to bundle multiple words together you need to surround the
        argument with quotes, as above.

        Once you've added a pattern, you need to enable it in a channel using one
        of [p]addwhitelist or [p]addblacklist, e.g.:
          ^automod2 addwhitelist "messages must start with a room code"

        If a channel has any whitelists, then text typed in the channel must match
        AT LEAST one whitelist, or it will be deleted. If ANY blacklist is matched
        the text will be deleted.

        You can see what patterns are enabled in a channel using [p]automod2 listrules
        """
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
        output += self.patternsToTableText(whitelists)
        output += '\n\n\n'
        output += 'Blacklists:\n'
        output += self.patternsToTableText(blacklists)
        await boxPagifySay(self.bot.say, output)

    @automod2.command(name="listpatterns", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def listPatterns(self, ctx):
        patterns = self.settings.getPatterns(ctx)
        output = 'AutoMod patterns for this server\n\n'
        output += self.patternsToTableText(patterns.values())
        await boxPagifySay(self.bot.say, output)

    @automod2.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def imagelimit(self, ctx, limit : int):
        """Prevents users from spamming images in a channel.

        If a user attempts to link/attach more than <limit> images in the active channel
        within the the lookback window (currently 5), all those messages are deleted.

        Set to 0 to clear.
        """
        self.settings.setImageLimit(ctx, limit)
        if limit == 0:
            await self.bot.say(inline('Limit cleared'))
        else:
            await self.bot.say(inline('I will delete excess images in this channel'))


    async def mod_message_images(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return

        ctx = CtxWrapper(message)
        image_limit = self.settings.getImageLimit(ctx)
        if image_limit == 0:
            return

        key = (message.channel.id, message.author.id)
        self.channel_user_logs[key].append(message)

        user_logs = self.channel_user_logs[key]
        count = 0
        for m in user_logs:
            count += linked_img_count(m)
        if count <= image_limit:
            return

        for m in list(user_logs):
            if linked_img_count(m) > 0:
                try:
                    await self.bot.delete_message(m)
                except:
                    pass
                try:
                    user_logs.remove(m)
                except:
                    pass

        msg = m.author.mention + inline(' Upload multiple images to an imgur gallery #endimagespam')
        alert_msg = await self.bot.send_message(message.channel, msg)
        await asyncio.sleep(10)
        await self.bot.delete_message(alert_msg)

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

    def patternsToTableText(self, patterns):
        tbl = prettytable.PrettyTable(["Rule Name", "Include regex", "Exclude regex"])
        tbl.hrules = prettytable.HEADER
        tbl.vrules = prettytable.NONE
        tbl.align = "l"

        for value in patterns:
            tbl.add_row([value['name'], value['include_pattern'], value['exclude_pattern']])
        return tbl.get_string()


def matchesPattern(pattern, txt):
    if not len(pattern):
        return False

    try:
        if pattern[0] == pattern[-1] == ':':
            check_method = globals().get(pattern[1:-1])
            if check_method:
                return check_method(txt)
    except:
        print('Failed method pattern match:', pattern, txt)
        return False

    p = re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return p.match(txt)


def starts_with_code(txt):
    # ignore spaces before or in code
    txt = txt.replace(' ', '')
    # ignore tilde, some users use them to cross out rooms
    txt = txt.replace('~', '')
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
    bot.add_listener(n.mod_message_images, "on_message")
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
                'image_limit': 0,
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
        for channel_id, channel_config in server['channels'].items():
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

    def getImageLimit(self, ctx):
        channel = self.getChannel(ctx)
        return channel.get('image_limit', 0)

    def setImageLimit(self, ctx, image_limit):
        channel = self.getChannel(ctx)
        channel['image_limit'] = image_limit
        self.save_settings()
