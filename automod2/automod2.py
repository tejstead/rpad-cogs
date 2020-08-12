"""
Lets you create patterns to match against messages and apply them as whitelists
or blacklists to a channel.

If a violation occurs, the message will be deleted and the user notified.
"""

from _datetime import datetime
from collections import defaultdict
from collections import deque
import copy
import discord
from discord.ext import commands
import os
import prettytable
import re
from time import time

from __main__ import send_cmd_help
from __main__ import settings

from . import rpadutils
from .rpadutils import *
from .rpadutils import CogSettings
from .utils import checks
from .utils.dataIO import fileIO
from .utils.settings import Settings


LOGS_PER_CHANNEL_USER = 5

AUTOMOD_HELP = """
Automod works by creating named global patterns, and then applying them in
specific channels as either whitelist or blacklist rules. This allows you
to customize what text can be typed in a channel. Text from moderators is
always ignored by this cog.

Check out [p]automod2 patterns to see the current server-specific list of patterns.

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

You can see the configuration for the server using [p]automod2 list

You can also prevent users from spamming images using [p]automod2 imagelimit
"""
EMOJIS = {
    'tips': [
        '\N{THUMBS UP SIGN}',
        '\N{THUMBS DOWN SIGN}',
        '\N{EYES}',
    ]
}

def linked_img_count(message):
    return len(message.embeds) + len(message.attachments)


def mod_or_perms(ctx, **perms):
    try:
        server = ctx.message.server
        mod_role = settings.get_server_mod(server).lower()
        admin_role = settings.get_server_admin(server).lower()
        return checks.role_or_permissions(ctx, lambda r: r.name.lower() in (mod_role, admin_role), **perms)
    except:
        return False


class CtxWrapper:
    def __init__(self, msg, bot):
        self.message = msg
        self.bot = bot


class AutoMod2:
    def __init__(self, bot):
        self.bot = bot

        self.settings = AutoMod2Settings("automod2")
        self.settings.cleanup()
        self.channel_user_logs = defaultdict(lambda: deque(maxlen=LOGS_PER_CHANNEL_USER))

        self.server_user_last = defaultdict(dict)
        self.server_phrase_last = defaultdict(dict)

    @commands.command()
    @checks.mod_or_permissions(manage_server=True)
    async def automodhelp(self):
        """Sends you info on how to use automod."""
        for page in pagify(AUTOMOD_HELP, delims=['\n'], shorten_by=8):
            await self.bot.whisper(box(page))

    @commands.group(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def automod2(self, context):
        """AutoMod2 tools.

        This cog works by creating named global patterns, and then applying them in
        specific channels as either whitelist or blacklist rules.

        For more information, use [p]automodhelp
        """
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @automod2.command(name="addpattern", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addPattern(self, ctx, name, include_pattern, exclude_pattern='', error=None):
        """Add a pattern for use in this server."""
        if error is not None:
            await self.bot.say(inline('Too many inputs detected, check your quotes'))
            return
        try:
            re.compile(include_pattern)
            re.compile(exclude_pattern)
        except Exception as ex:
            raise rpadutils.ReportableError(str(ex))
        self.settings.addPattern(ctx, name, include_pattern, exclude_pattern)
        await self.bot.say(inline('Added pattern'))

    @automod2.command(name="rmpattern", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmPattern(self, ctx, *, name):
        """Remove a pattern from this server. Pattern must not be in use."""
        self.settings.rmPattern(ctx, name)
        await self.bot.say(inline('Removed pattern'))

    @automod2.command(name="addwhitelist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addWhitelist(self, ctx, *, name):
        """Add the named pattern as a whitelist for this channel."""
        self.settings.addWhitelist(ctx, name)
        await self.bot.say(inline('Added whitelist config for: ' + name))

    @automod2.command(name="rmwhitelist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmWhitelist(self, ctx, *, name):
        """Remove the named pattern as a whitelist for this channel."""
        self.settings.rmWhitelist(ctx, name)
        await self.bot.say(inline('Removed whitelist config for: ' + name))

    @automod2.command(name="addblacklist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addBlacklist(self, ctx, *, name):
        """Add the named pattern as a blacklist for this channel."""
        self.settings.addBlacklist(ctx, name)
        await self.bot.say(inline('Added blacklist config for: ' + name))

    @automod2.command(name="rmblacklist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmBlacklist(self, ctx, *, name):
        """Remove the named pattern as a blacklist for this channel."""
        self.settings.rmBlacklist(ctx, name)
        await self.bot.say(inline('Removed blacklist config for: ' + name))

    @automod2.command(name="list", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def list(self, ctx):
        """List the whitelist/blacklist configuration for the current channel."""
        output = 'AutoMod configs\n'
        channels = self.settings.getChannels(ctx)
        for channel_id, config in channels.items():
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue

            whitelists = config['whitelist']
            blacklists = config['blacklist']
            image_limit = config.get('image_limit', 0)
            auto_emojis_type = config.get('auto_emojis_type', None)
            if len(whitelists + blacklists) + image_limit == 0 and not auto_emojis_type:
                continue

            output += '\n#{}'.format(channel.name)
            output += '\n\tWhitelists'
            for name in whitelists:
                output += '\n\t\t{}'.format(name)
            output += '\n\tBlacklists'
            for name in blacklists:
                output += '\n\t\t{}'.format(name)
            output += '\n\tImage Limit: {}'.format(image_limit)
            output += '\n\tAuto Emojis Type: {}'.format(auto_emojis_type)
        await boxPagifySay(self.bot.say, output)

    @automod2.command(name="patterns", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def patterns(self, ctx):
        """List the registered patterns."""
        patterns = self.settings.getPatterns(ctx)
        output = 'AutoMod patterns for this server\n\n'
        output += self.patternsToTableText(patterns.values())
        await boxPagifySay(self.bot.say, output)

    @automod2.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def imagelimit(self, ctx, limit: int):
        """Prevents users from spamming images in a channel.

        If a user attempts to link/attach more than <limit> images in the active channel
        within the the lookback window (currently 5), all those messages are deleted.

        Set to 0 to clear.

        Set to -1 to enable image only.
        """
        self.settings.setImageLimit(ctx, limit)
        if limit == 0:
            await self.bot.say(inline('Limit cleared'))
        elif limit == -1:
            await self.bot.say(inline('I will only allow images in this channel'))
        else:
            await self.bot.say(inline('I will delete excess images in this channel'))

    async def mod_message_images(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return
        ctx = CtxWrapper(message, self.bot)
        image_limit = self.settings.getImageLimit(ctx)
        if image_limit == 0:
            return
        elif image_limit > 0:
            if mod_or_perms(ctx, manage_messages=True):
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
        else:
            if mod_or_perms(ctx, manage_messages=True):
                return
            if len(message.embeds) or len(message.attachments):
                return
            msg_template = box('Your message in {} was deleted for not containing an image')
            msg = msg_template.format(message.channel.name)
            await self.deleteAndReport(message, msg)
                
    async def mod_message_edit(self, before, after):
        await self.mod_message(after)

    async def mod_message(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return

        ctx = CtxWrapper(message, self.bot)
        if mod_or_perms(ctx, manage_messages=True):
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

            msg = msg_template.format(message.channel.name,
                                      ','.join(failed_whitelists), msg_content)
            await self.deleteAndReport(message, msg)

    @automod2.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def autoemojis(self, ctx, key: str = None):
        """Will automatically add a set of emojis to all messages sent in this channel.

        Currently supported: tips

        Include the text [noemojis] to suppress emoji addition
        """
        if not key:
            self.settings.setAutoEmojis(ctx, None)
            await self.bot.say(inline('Auto emojis cleared'))
            return
        key = key.lower()
        if key not in EMOJIS:
            await self.bot.say(inline('Unknown key'))
            return
        self.settings.setAutoEmojis(ctx, key)
        await self.bot.say(inline('Auto Emojis for this channel configured!'))

    async def add_auto_emojis(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return
        ctx = CtxWrapper(message, self.bot)
        key = self.settings.getAutoEmojis(ctx)
        if not key:
            return
        if '[noemojis]' in message.content:
            return
        emoji_list = EMOJIS[key]
        for emoji in emoji_list:
            await self.bot.add_reaction(message, emoji)

    @commands.group(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def watchdog(self, ctx):
        """User monitoring tools."""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @watchdog.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def printconfig(self, ctx):
        """Print the watchdog configuration."""
        server_id = ctx.message.server.id
        msg = 'Watchdog config:'
        watchdog_channel_id = self.settings.getWatchdogChannel(server_id)
        if watchdog_channel_id:
            watchdog_channel = self.bot.get_channel(watchdog_channel_id)
            if watchdog_channel:
                msg += '\nChannel: ' + watchdog_channel.name
            else:
                msg += '\nChannel configured but not found'
        else:
            msg += '\nChannel not set'

        msg += '\n\nUsers'
        for user_id, user_settings in self.settings.getWatchdogUsers(server_id).items():
            user_cooldown = user_settings['cooldown']
            request_user_id = user_settings['request_user_id']
            reason = user_settings['reason'] or 'no reason'

            request_user = ctx.message.server.get_member(request_user_id)
            request_user_txt = request_user.name if request_user else '???'
            member = ctx.message.server.get_member(user_id)
            if user_cooldown and member:
                msg += '\n{} ({})\n\tcooldown {}\n\tby {} because [{}]'.format(
                    member.name, member.id, user_cooldown, request_user_txt, reason)

        msg += '\n\nPhrases'
        for name, phrase_settings in self.settings.getWatchdogPhrases(server_id).items():
            phrase_cooldown = phrase_settings['cooldown']
            request_user_id = phrase_settings['request_user_id']
            phrase = phrase_settings['phrase']

            request_user = ctx.message.server.get_member(request_user_id)
            request_user_txt = request_user.name if request_user else '???'
            if phrase_cooldown:
                msg += '\n{} -> {}\n\tcooldown {}\n\tby {}'.format(
                    name, phrase, phrase_cooldown, request_user_txt)

        for page in pagify(msg):
            await self.bot.say(box(page))

    @watchdog.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def user(self, ctx, user: discord.User, cooldown: int=None, *, reason: str=''):
        """Keep an eye on a user.

        Whenever the user speaks in this server, a note will be printed to the watchdog
        channel, subject to the specified cooldown in seconds. Set to 0 to clear.
        """
        server_id = ctx.message.server.id
        if cooldown is None:
            user_settings = self.settings.getWatchdogUsers(server_id).get(user.id, {})
            existing_cd = user_settings.get('cooldown', 0)
            if existing_cd == 0:
                await self.bot.say(inline('No watchdog for that user'))
            else:
                await self.bot.say(inline('Watchdog set with cooldown of {} seconds'.format(existing_cd)))
        else:
            self.settings.setWatchdogUser(
                server_id, user.id, ctx.message.author.id, cooldown, reason)
            if cooldown == 0:
                await self.bot.say(inline('Watchdog cleared for {}'.format(user.name)))
            else:
                await self.bot.say(inline('Watchdog set on {} with cooldown of {} seconds'.format(user.name, cooldown)))

    @watchdog.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def phrase(self, ctx, name: str, cooldown: int, *, phrase: str=None):
        """Keep an eye out for a phrase (regex).

        Whenever the regex is matched, a note will be printed to the watchdog
        channel, subject to the specified cooldown in seconds.

        Name is descriptive. Set a cooldown of 0 to clear.
        """
        server_id = ctx.message.server.id

        if cooldown == 0:
            self.settings.setWatchdogPhrase(
                server_id, name, None, None, None)
            await self.bot.say(inline('Watchdog phrase cleared for {}'.format(name)))
            return

        try:
            re.compile(phrase)
        except Exception as ex:
            raise rpadutils.ReportableError(str(ex))

        if cooldown < 300:
            await self.bot.say(inline('Overriding cooldown to minimum'))
            cooldown = 300
        self.settings.setWatchdogPhrase(server_id, name, ctx.message.author.id, cooldown, phrase)
        self.server_phrase_last[server_id][name] = None
        await self.bot.say(inline('Watchdog named {} set on {} with cooldown of {} seconds'.format(name, phrase, cooldown)))

    @watchdog.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def channel(self, ctx, channel: discord.Channel):
        """Set the announcement channel."""
        server_id = ctx.message.server.id
        self.settings.setWatchdogChannel(server_id, channel.id)
        await self.bot.say(inline('Watchdog channel set'))

    async def mod_message_watchdog(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return
        if self.settings.getWatchdogChannel(message.server.id) is None:
            return

        await self.mod_message_watchdog_user(message)
        await self.mod_message_watchdog_phrase(message)

    async def mod_message_watchdog_user(self, message):
        user_id = message.author.id
        server_id = message.server.id
        watchdog_channel_id = self.settings.getWatchdogChannel(server_id)
        user_settings = self.settings.getWatchdogUsers(server_id).get(user_id)

        if user_settings is None:
            return

        cooldown = user_settings['cooldown']
        if cooldown <= 0:
            return

        request_user_id = user_settings['request_user_id']
        reason = user_settings['reason'] or 'no reason'

        request_user = message.server.get_member(request_user_id)
        request_user_txt = request_user.mention if request_user else '???'

        now = datetime.utcnow()
        last_spoke_at = self.server_user_last[server_id].get(user_id)
        self.server_user_last[server_id][user_id] = now
        time_since = (now - last_spoke_at).total_seconds() if last_spoke_at else 9999

        report = time_since > cooldown
        if not report:
            return

        output_msg = '**Watchdog:** {} spoke in {} ({} monitored because [{}])\n{}'.format(
            message.author.mention, message.channel.mention,
            request_user_txt, reason, box(message.clean_content))
        await self._watchdog_print(watchdog_channel_id, output_msg)

    async def mod_message_watchdog_phrase(self, message):
        server_id = message.server.id
        watchdog_channel_id = self.settings.getWatchdogChannel(server_id)

        for phrase_settings in self.settings.getWatchdogPhrases(server_id).values():
            name = phrase_settings['name']
            cooldown = phrase_settings['cooldown']
            request_user_id = phrase_settings['request_user_id']
            phrase = phrase_settings['phrase']

            if cooldown <= 0:
                continue

            now = datetime.utcnow()
            last_spoke_at = self.server_phrase_last[server_id].get(name)
            time_since = (now - last_spoke_at).total_seconds() if last_spoke_at else 9999

            report = time_since > cooldown
            if not report:
                continue

            p = re.compile(phrase, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if p.match(message.clean_content):
                self.server_phrase_last[server_id][name] = now
                output_msg = '**Watchdog:** {} spoke in {} `(rule [{}] matched phrase [{}])`\n{}'.format(
                    message.author.mention, message.channel.mention,
                    name, phrase, box(message.clean_content))
                await self._watchdog_print(watchdog_channel_id, output_msg)
                return

    async def _watchdog_print(self, watchdog_channel_id, output_msg):
        try:
            watchdog_channel = self.bot.get_channel(watchdog_channel_id)
            await self.bot.send_message(watchdog_channel, output_msg)
        except Exception as ex:
            print('failed to watchdog', str(ex))

    async def deleteAndReport(self, delete_msg, outgoing_msg):
        try:
            await self.bot.delete_message(delete_msg)
            await self.bot.send_message(delete_msg.author, outgoing_msg)
        except Exception as e:
            print('Failure while deleting message from {}, tried to send : {}'.format(
                delete_msg.author.name, outgoing_msg))
            print(str(e))

    def patternsToTableText(self, patterns):
        tbl = prettytable.PrettyTable(["Rule Name", "Include regex", "Exclude regex"])
        tbl.hrules = prettytable.HEADER
        tbl.vrules = prettytable.NONE
        tbl.align = "l"

        for value in patterns:
            tbl.add_row([value['name'], value['include_pattern'], value['exclude_pattern']])

        return rpadutils.strip_right_multiline(tbl.get_string())


def matchesPattern(pattern, txt):
    if not len(pattern):
        return False

    try:
        if pattern[0] == pattern[-1] == ':':
            check_method = globals().get(pattern[1:-1])
            if check_method:
                return check_method(txt)
    except:
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
    n = AutoMod2(bot)
    bot.add_listener(n.mod_message_images, "on_message")
    bot.add_listener(n.add_auto_emojis, "on_message")
    bot.add_listener(n.mod_message, "on_message")
    bot.add_listener(n.mod_message_edit, "on_message_edit")
    bot.add_listener(n.mod_message_watchdog, "on_message")
    bot.add_cog(n)


class AutoMod2Settings(CogSettings):
    def make_default_settings(self):
        config = {
            'configs': {}
        }
        return config

    def cleanup(self):
        for server in self.serverConfigs().values():
            channels = server['channels']
            for channel_id in list(channels.keys()):
                channel = channels[channel_id]
                if any([channel.get(x) for x in ['whitelist', 'blacklist', 'image_limit', 'auto_emojis_type']]):
                    continue
                channels.pop(channel_id)

    def serverConfigs(self):
        return self.bot_settings['configs']

    def getServer(self, ctx, server_id=None):
        configs = self.serverConfigs()
        server_id = server_id or ctx.message.server.id
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
                'auto_emojis_type': None
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
            raise rpadutils.ReportableError("That pattern is in use")
        self.getPatterns(ctx).pop(name)
        self.save_settings()

    def addRule(self, ctx, name, list_type):
        patterns = self.getPatterns(ctx)
        if name not in patterns:
            raise rpadutils.ReportableError("Couldn't find rule name")
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

    def getAutoEmojis(self, ctx):
        channel = self.getChannel(ctx)
        return channel.get('auto_emojis_type', None)

    def setAutoEmojis(self, ctx, key):
        channel = self.getChannel(ctx)
        channel['auto_emojis_type'] = key
        self.save_settings()

    def getWatchdog(self, server_id):
        server = self.getServer(None, server_id)
        key = 'watchdog'
        if key not in server:
            server[key] = {}
        return server[key]

    def getWatchdogChannel(self, server_id):
        watchdog = self.getWatchdog(server_id)
        return watchdog.get('announce_channel')

    def setWatchdogChannel(self, server_id, channel_id):
        watchdog = self.getWatchdog(server_id)
        watchdog['announce_channel'] = channel_id
        self.save_settings()

    def getWatchdogUsers(self, server_id):
        watchdog = self.getWatchdog(server_id)
        key = 'users'
        if key not in watchdog:
            watchdog[key] = {}
        return watchdog[key]

    def setWatchdogUser(self, server_id, user_id, request_user_id, cooldown_secs, reason):
        watchdog_users = self.getWatchdogUsers(server_id)
        if cooldown_secs:
            watchdog_users[user_id] = {
                'request_user_id': request_user_id,
                'cooldown': cooldown_secs,
                'reason': reason,
            }
        else:
            watchdog_users.pop(user_id, None)
        self.save_settings()

    def getWatchdogPhrases(self, server_id):
        watchdog = self.getWatchdog(server_id)
        key = 'phrases'
        if key not in watchdog:
            watchdog[key] = {}
        return watchdog[key]

    def setWatchdogPhrase(self, server_id, name, request_user_id, cooldown_secs, phrase):
        watchdog_phrases = self.getWatchdogPhrases(server_id)
        if cooldown_secs:
            watchdog_phrases[name] = {
                'name': name,
                'request_user_id': request_user_id,
                'cooldown': cooldown_secs,
                'phrase': phrase,
            }
        else:
            watchdog_phrases.pop(name, None)
        self.save_settings()
