import asyncio
from collections import defaultdict
from collections import deque
import copy
from datetime import datetime
import os
import random
import re
from time import time

from cachetools import LRUCache
import discord
from discord.ext import commands

from __main__ import send_cmd_help
from __main__ import settings

from .rpadutils import *
from .utils import checks
from .utils.cog_settings import *
from .utils.dataIO import fileIO
from .utils.settings import Settings


DEFAULT_SUPERMOD_COUNT = 5

SUPERMOD_COG = None

def is_supermod_check(ctx):
    server = ctx.message.server
    author = ctx.message.author
    supermod_role = SUPERMOD_COG.get_supermod_role(server)
    if supermod_role is None:
        return False
    else:
        return supermod_role in author.roles

def is_supermod():
    return commands.check(is_supermod_check)

class SuperMod:
    def __init__(self, bot):
        self.bot = bot
        self.settings = SuperModSettings("supermod")

        self.server_id_to_last_spoke = defaultdict(dict)

        global SUPERMOD_COG
        SUPERMOD_COG = self

        self.server_id_to_quiet_user_ids = defaultdict(set)

    async def refresh_supermod(self):
        await self.bot.wait_until_ready()
        while self == self.bot.get_cog('SuperMod'):
            try:
                await self.do_refresh_supermod()
            except Exception as e:
                traceback.print_exc()

            await asyncio.sleep(self.settings.getRefreshTimeSec())

    def get_supermod_role(self, server):
        if not server:
            return
        supermod_role_id = self.settings.getSupermodRole(server.id)
        if supermod_role_id:
            return get_role_from_id(self.bot, server, supermod_role_id)
        else:
            return None

    def check_supermod(self, member : discord.Member, supermod_role : discord.Role):
        return supermod_role in member.roles if supermod_role else False

    async def add_supermod(self, member : discord.Member, supermod_role : discord.Role):
        if supermod_role and not self.check_supermod(member, supermod_role):
            await self.bot.add_roles(member, supermod_role)

    async def remove_supermod(self, member : discord.Member, supermod_role : discord.Role):
        if supermod_role and self.check_supermod(member, supermod_role):
            await self.bot.remove_roles(member, supermod_role)

    def get_current_supermods(self, server : discord.Server, supermod_role : discord.Role):
        if supermod_role is None:
            return []
        return [member for member in server.members if self.check_supermod(member, supermod_role)]

    def get_user_name(self, server, user_id):
        member = server.get_member(user_id)
        return "{} ({})".format(member.name if member else '<unknown>', user_id)

    def get_channel_name(self, server, channel_id):
        channel = server.get_channel(channel_id)
        return "{} ({})".format(channel.name if channel else '<unknown>', channel_id)

    async def do_modlog(self, server_id, log_text, do_say=True):
        mod_log_channel_id = self.settings.getModlogChannel(server_id)
        if mod_log_channel_id:
            try:
                await self.bot.send_message(discord.Object(mod_log_channel_id), log_text)
            except:
                print("Couldn't log to " + mod_log_channel_id)

        if do_say:
            await self.bot.say(log_text)

    async def do_refresh_supermod(self):
        for server_id, server in self.settings.servers().items():
            if not self.settings.serverEnabled(server_id):
                continue

            server = self.bot.get_server(server_id)
            if server is None:
                continue

            supermod_role = self.get_supermod_role(server)
            if supermod_role is None:
                continue

            output = 'Refresh started'

            permanent_supermods = self.settings.permanentSupermod(server_id)
            for member in self.get_current_supermods(server, supermod_role):
                if member.id in permanent_supermods:
                    continue
                await self.remove_supermod(member, supermod_role)
                output += '\nRemoved {} from {}'.format(supermod_role.name, member.name)


            quiet_users = self.server_id_to_quiet_user_ids[server_id]
            for user_id in quiet_users:
                output += '\nRemoved quiet time from {}'.format(member.name)
            quiet_users.clear()

            users_spoken = self.server_id_to_last_spoke[server_id].keys()

            blacklisted_supermods = self.settings.blacklistUsers(server_id)
            ignored_supermods = self.settings.ignoreUsers()

            users_spoken = filter(lambda user_id: user_id not in blacklisted_supermods and user_id not in ignored_supermods, users_spoken)
            users_spoken = list(users_spoken)

            supermod_count = self.settings.getSupermodCount(server_id)
            new_mods = random.sample(users_spoken, min(len(users_spoken), supermod_count))
            self.server_id_to_last_spoke[server_id].clear()

            new_mods += permanent_supermods
            new_mods = set(new_mods)

            for new_mod in new_mods:
                member = server.get_member(new_mod)
                if member is None:
                    print('Failed to look up member for id', new_mod)
                    continue

                if self.check_supermod(member, supermod_role):
                    continue

                await self.add_supermod(member, supermod_role)
                output += '\nAdded {} to {}'.format(supermod_role.name, member.name)

            await self.do_modlog(server_id, box(output), do_say=False)

    async def log_message(self, message):
        if not message.server or not message.channel:
            return

        server_id = message.server.id
        channel_id = message.channel.id

        server_enabled = self.settings.serverEnabled(server_id)
        discussion_channel_ids = self.settings.discussionChannels(server_id)
        if not server_enabled or channel_id not in discussion_channel_ids:
            return

        user_id = message.author.id
        if user_id == self.bot.user.id:
            return

        if user_id in self.settings.ignoreUsers():
            return

        self.server_id_to_last_spoke[server_id][user_id] = datetime.now()

        if user_id in self.server_id_to_quiet_user_ids[server_id]:
            try:
                await self.bot.delete_message(message)
                await self.bot.send_message(message.channel, 'SHHHH {} you are on quiet time!'.format(message.author.mention))
            except Exception as e:
                print(e)

    @commands.group(pass_context=True)
    async def supermod(self, context):
        """Automagical selection of moderators for your server."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @supermod.command(pass_context=True)
    @checks.is_owner()
    async def setRefreshTime(self, ctx, refresh_time_sec : int):
        """Set the global refresh period for SuperMod, in seconds (global)."""
        self.settings.setRefreshTimeSec(refresh_time_sec)
        await self.bot.say(inline('Done, make sure to reload'))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def addPermanentSupermod(self, ctx, user : discord.Member):
        """Ensures a user is always selected as SuperMod."""
        self.settings.addPermanentSupermod(ctx.message.server.id, user.id)
        await self.bot.say(inline('Done'))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def rmPermanentSupermod(self, ctx, user : discord.Member):
        """Removes a user from the always SuperMod list."""
        self.settings.rmPermanentSupermod(ctx.message.server.id, user.id)
        await self.bot.say(inline('Done'))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def toggleServerEnabled(self, ctx):
        """Enables or disables SuperMod on this server."""
        now_enabled = self.settings.toggleServerEnabled(ctx.message.server.id)
        await self.bot.say(inline('Server now {}'.format('enabled' if now_enabled else 'disabled')))

    @supermod.command(pass_context=True)
    @checks.is_owner()
    async def forceRefresh(self, ctx):
        """Forces an immediate refresh of the SuperMods."""
        await self.do_refresh_supermod()
        await self.bot.say(inline('Done'))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def setSupermodCount(self, ctx, count : int):
        """Set the number of automatically selected SuperMods on this server."""
        self.settings.setSupermodCount(ctx.message.server.id, count)
        await self.bot.say(inline('Done'))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def setModLogChannel(self, ctx, channel : discord.Channel):
        """Sets the channel used for printing moderation logs."""
        self.settings.setModlogChannel(ctx.message.server.id, channel.id)
        await self.bot.say(inline('Done'))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def clearModLogChannel(self, ctx):
        """Clears the channel used for printing moderation logs."""
        self.settings.clearModlogChannel(ctx.message.server.id)
        await self.bot.say(inline('Done'))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def setSupermodRole(self, ctx, role_name : str):
        """Sets the role that designates a user as SuperMod (make sure to hoist it)."""
        role = get_role(ctx.message.server.roles, role_name)
        self.settings.setSupermodRole(ctx.message.server.id, role.id)
        await self.bot.say(inline('Done'))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def clearSupermodRole(self, ctx):
        """Clears the role that designates a user as SuperMod."""
        self.settings.clearSupermodRole(ctx.message.server.id)
        await self.bot.say(inline('Done'))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addDiscussionChannel(self, ctx, channel : discord.Channel):
        """Marks a channel as containing discussion.

        Discussion channels are automatically monitored for activity. Users active in these
        channels have a chance of becoming a SuperMod.

        Discussion channels are also eligible for SuperMod activities like renaming and
        topic changing.
        """
        self.settings.addDiscussionChannel(ctx.message.server.id, channel.id)
        await self.do_modlog(ctx.message.server.id, inline('More SuperMod fun time in {}'.format(channel.name)))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmDiscussionChannel(self, ctx, channel : discord.Channel):
        """Clears the discussion status from a channel."""
        self.settings.rmDiscussionChannel(ctx.message.server.id, channel.id)
        await self.do_modlog(ctx.message.server.id, inline('OK, no SuperMod fun time in {}'.format(channel.name)))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addBlacklistedUser(self, ctx, member : discord.Member):
        """Removes SuperMod status from a user (if they have it) and ensures they won't be selected."""
        self.settings.addBlacklistUser(ctx.message.server.id, member.id)
        await self.do_modlog(ctx.message.server.id, inline('{} was naughty, no SuperMod fun time for them'.format(member.name)))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmBlacklistedUser(self, ctx, member : discord.Member):
        """Re-enable SuperMod selection for a user."""
        self.settings.rmBlacklistUser(ctx.message.server.id, member.id)
        await self.do_modlog(ctx.message.server.id, inline('{} was forgiven, they can SuperMod again}'.format(member.name)))

    @supermod.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def dump(self, ctx):
        """Print the SuperMod configuration for this server."""
        server = ctx.message.server
        server_id = server.id

        refresh_time_sec = self.settings.getRefreshTimeSec()
        users_spoken = self.server_id_to_last_spoke[server_id]
        server_enabled = self.settings.serverEnabled(server_id)
        supermod_count = self.settings.getSupermodCount(server_id)
        supermod_role = self.get_supermod_role(server)
        mod_log_channel_id = self.settings.getModlogChannel(server_id)
        discussion_channel_ids = self.settings.discussionChannels(server_id)
        permanent_supermods = self.settings.permanentSupermod(server_id)
        current_supermods = self.get_current_supermods(server, supermod_role)
        blacklisted_supermods = self.settings.blacklistUsers(server_id)
        ignored_supermods = self.settings.ignoreUsers()
        quiet_users = self.server_id_to_quiet_user_ids[server_id]


        supermod_role_output = supermod_role.name if supermod_role else 'Not configured'

        output = 'SuperMod configuration:\n'
        output += '\nrefresh_sec: {}'.format(refresh_time_sec)
        output += '\nusers spoken: {}'.format(len(users_spoken))
        output += '\nsupermod count: {}'.format(supermod_count)
        output += '\nsupermod role: {}'.format(supermod_role_output)
        output += '\nserver enabled: {}'.format(server_enabled)
        output += '\nmodlog channel: {}'.format(self.get_channel_name(server, mod_log_channel_id))

        output += '\ndiscussion channels:'
        for channel_id in discussion_channel_ids:
            output += '\n\t{}'.format(self.get_channel_name(server, channel_id))

        output += '\npermanent supermods:'
        for user_id in permanent_supermods:
            output += '\n\t{}'.format(self.get_user_name(server, user_id))

        output += '\ncurrent supermods:'
        for member in current_supermods:
            output += '\n\t{}'.format(self.get_user_name(server, member.id))

        output += '\nblacklisted users:'
        for user_id in blacklisted_supermods:
            output += '\n\t{}'.format(self.get_user_name(server, user_id))

        output += '\nignored users:'
        for user_id in ignored_supermods:
            output += '\n\t{}'.format(self.get_user_name(server, user_id))

        output += '\nquiet users:'
        for user_id in quiet_users:
            output += '\n\t{}'.format(self.get_user_name(server, user_id))


        await self.bot.say(box(output))

    @supermod.command(pass_context=True, no_pm=True)
    @is_supermod()
    async def rename(self, ctx, member : discord.Member, *, new_name : str=None):
        """You're a SuperMod! Set the nickname on a user."""
        author_name = ctx.message.author.name
        server_id = ctx.message.server.id

        if member.id in self.settings.ignoreUsers():
            msg = "Sorry {}, {} hates SuperMod so I won't change their name".format(author_name, member.name)
            await self.do_modlog(server_id, inline(msg))

        member_old_name = member.name
        msg_template = None
        try:
            await self.bot.change_nickname(member, new_name)
            if new_name:
                msg_template = "SuperMod {} renamed {} to {}"
            else:
                msg_template = "SuperMod {} cleared nickname for {}"
        except Exception as e:
            msg_template = "Sorry {} but I couldn't change the name of {} to {}"

        msg = msg_template.format(author_name, member_old_name, new_name)
        await self.do_modlog(server_id, inline(msg))

    @supermod.command(pass_context=True, no_pm=True)
    @is_supermod()
    async def quiet(self, ctx, member : discord.Member):
        """You're a SuperMod! Put someone in time-out."""
        author_name = ctx.message.author.name
        server = ctx.message.server
        server_id = server.id

        if member.id in self.settings.ignoreUsers():
            msg = "Sorry {}, {} hates SuperMod so I won't put them in quiet time".format(author_name, member.name)
            await self.do_modlog(server_id, inline(msg))
            return

        supermod_role = self.get_supermod_role(server)
        if self.check_supermod(member, supermod_role):
            msg = "Sorry {}, {} is a SuperMod so I can't quiet them".format(author_name, member.name)
            await self.do_modlog(server_id, inline(msg))
            return

        quiet_users = self.server_id_to_quiet_user_ids[server_id].add(member.id)
        msg_template = "SuperMod {} put {} in time out"

        msg = msg_template.format(author_name, member.name)
        await self.do_modlog(server_id, inline(msg))

    @supermod.command(pass_context=True, no_pm=True)
    @is_supermod()
    async def chat(self, ctx, *, new_channel_name):
        """You're a SuperMod! Change the channel name."""
        server_id = ctx.message.server.id
        channel = ctx.message.channel
        channel_id = channel.id
        old_channel_name = channel.name
        discussion_channel_ids = self.settings.discussionChannels(server_id)

        msg_template = None

        if channel_id not in discussion_channel_ids:
            msg_template = "Sorry {} but I can't rename channel {} to {} because it is not a discussion channel"
        else:
            try:
                await self.bot.edit_channel(channel, name=new_channel_name)
                msg_template = "SuperMod {} renamed channel {} to {}"
            except Exception as e:
                msg_template = "Sorry {} but I couldn't rename channel {} to {}"

        msg = msg_template.format(ctx.message.author.name, old_channel_name, new_channel_name)
        await self.do_modlog(server_id, inline(msg))

    @supermod.command(pass_context=True, no_pm=True)
    @is_supermod()
    async def topic(self, ctx, *, new_channel_topic):
        """You're a SuperMod! Change the channel topic."""
        server_id = ctx.message.server.id
        channel = ctx.message.channel
        channel_id = channel.id
        discussion_channel_ids = self.settings.discussionChannels(server_id)

        msg_template = None

        if channel_id not in discussion_channel_ids:
            msg_template = "Sorry {} but I can't change channel topic for {} to {} because it is not a discussion channel"
        else:
            try:
                await self.bot.edit_channel(channel, topic=new_channel_topic)
                msg_template = "SuperMod {} changed channel topic for {} to {}"
            except Exception as e:
                msg_template = "Sorry {} but I couldn't change channel topic for {} to {}"

        msg = msg_template.format(ctx.message.author.name, channel.name, new_channel_topic)
        await self.do_modlog(ctx.message.server.id, inline(msg))

    @supermod.command(pass_context=True)
    async def ignoreme(self, ctx):
        """I guess you can set this if you don't like SuperMod, but why?"""
        author = ctx.message.author
        self.settings.addIgnoreUser(author.id)
        await self.bot.say(inline("I-It's not like I like you or anything... B-Baka! No more SuperMod for {}.".format(author.name)))

    @supermod.command(pass_context=True)
    async def noticeme(self, ctx):
        """You do like SuperMod! I knew you'd be back."""
        author = ctx.message.author
        self.settings.rmIgnoreUser(author.id)
        await self.bot.say(inline('Senpai noticed you! {} can SuperMod again.'.format(author.name)))

def setup(bot):
    n = SuperMod(bot)
    bot.loop.create_task(n.refresh_supermod())
    bot.add_listener(n.log_message, "on_message")
    bot.add_cog(n)

class SuperModSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'refresh_time_sec' : 10 * 60,
          'servers' : {},
        }
        return config


    def getRefreshTimeSec(self):
        return self.bot_settings['refresh_time_sec']

    def setRefreshTimeSec(self, time_sec):
        self.bot_settings['refresh_time_sec'] = int(time_sec)
        self.save_settings()

    def servers(self):
        key = 'servers'
        if key not in self.bot_settings:
            self.bot_settings[key] = {}
        return self.bot_settings[key]

    def getServer(self, server_id):
        servers = self.servers()
        if server_id not in servers:
            servers[server_id] = {}
        return servers[server_id]

    def permanentSupermod(self, server_id):
        key = 'permanent_supermods'
        server = self.getServer(server_id)
        if key not in server:
            server[key] = []
        return server[key]

    def addPermanentSupermod(self, server_id, user_id):
        supermods = self.permanentSupermod(server_id)
        if user_id not in supermods:
            supermods.append(user_id)
            self.save_settings()

    def rmPermanentSupermod(self, server_id, user_id):
        self.permanentSupermod(server_id).remove(user_id)
        self.save_settings()

    def ignoreUsers(self):
        key = 'ignore_users'
        if key not in self.bot_settings:
            self.bot_settings[key] = []
        return self.bot_settings[key]

    def addIgnoreUser(self, user_id):
        ignore_users = self.ignoreUsers()
        if user_id not in ignore_users:
            ignore_users.append(user_id)
            self.save_settings()

    def rmIgnoreUser(self, user_id):
        self.ignoreUsers().remove(user_id)
        self.save_settings()

    def blacklistUsers(self, server_id):
        server = self.getServer(server_id)
        key = 'blacklist_users'
        if key not in server:
            server[key] = []
        return server[key]

    def addBlacklistUser(self, server_id, user_id):
        blacklist_users = self.blacklistUsers(server_id)
        if user_id not in blacklist_users:
            blacklist_users.append(user_id)
            self.save_settings()

    def rmBlacklistUser(self, server_id, user_id):
        self.blacklistUsers(server_id).remove(user_id)
        self.save_settings()

    def serverEnabled(self, server_id):
        server = self.getServer(server_id)
        return server.get('enabled', False)

    def toggleServerEnabled(self, server_id):
        new_enabled = not self.serverEnabled(server_id)
        self.getServer(server_id)['enabled'] = new_enabled
        self.save_settings()
        return new_enabled

    def getSupermodCount(self, server_id):
        server = self.getServer(server_id)
        return server.get('supermod_count', DEFAULT_SUPERMOD_COUNT)

    def setSupermodCount(self, server_id, count):
        server = self.getServer(server_id)
        server['supermod_count'] = count
        self.save_settings()

    def getModlogChannel(self, server_id):
        server = self.getServer(server_id)
        return server.get('modlog_channel', None)

    def setModlogChannel(self, server_id, channel_id):
        server = self.getServer(server_id)
        server['modlog_channel'] = channel_id
        self.save_settings()

    def clearModlogChannel(self, server_id):
        server = self.getServer(server_id)
        server.pop('modlog_channel')
        self.save_settings()

    def getSupermodRole(self, server_id):
        server = self.getServer(server_id)
        return server.get('supermod_role', None)

    def setSupermodRole(self, server_id, role_id):
        server = self.getServer(server_id)
        server['supermod_role'] = role_id
        self.save_settings()

    def clearSupermodRole(self, server_id):
        server = self.getServer(server_id)
        server.pop('supermod_role')
        self.save_settings()

    def discussionChannels(self, server_id):
        key = 'discussion_channels'
        server = self.getServer(server_id)
        if key not in server:
            server[key] = []
        return server[key]

    def addDiscussionChannel(self, server_id, channel_id):
        channels = self.discussionChannels(server_id)
        if channel_id not in channels:
            channels.append(channel_id)
            self.save_settings()

    def rmDiscussionChannel(self, server_id, channel_id):
        channels = self.discussionChannels(server_id)
        if channel_id in channels:
            channels.remove(channel_id)
            self.save_settings()
