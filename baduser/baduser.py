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


LOGS_PER_USER = 10

class BadUser:
    def __init__(self, bot):
        self.bot = bot

        self.settings = BadUserSettings("baduser")
        self.logs = defaultdict(lambda: deque(maxlen=LOGS_PER_USER))

    @commands.group(pass_context=True, no_pm=True)
    async def baduser(self, context):
        """BadUser tools."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @baduser.command(name="addrole", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addRole(self, ctx, role):
        role = get_role(ctx.message.server.roles, role)
        self.settings.addPunishmentRole(ctx.message.server.id, role.id)
        await self.bot.say(inline('Added punishment role "' + role.name + '"'))

    @baduser.command(name="rmrole", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmRole(self, ctx, role):
        role = get_role(ctx.message.server.roles, role)
        self.settings.rmPunishmentRole(ctx.message.server.id, role.id)
        await self.bot.say(inline('Removed punishment role "' + role.name + '"'))

    @baduser.command(name="setchannel", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def setChannel(self, ctx, channel: discord.Channel):
        self.settings.updateChannel(ctx.message.server.id, channel.id)
        await self.bot.say(inline('Set the announcement channel'))

    @baduser.command(name="clearchannel", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def clearChannel(self, ctx):
        self.settings.updateChannel(ctx.message.server.id, None)
        await self.bot.say(inline('Cleared the announcement channel'))

    @baduser.command(name="list", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def list(self, ctx):
        role_ids = self.settings.getPunishmentRoles(ctx.message.server.id)
        output = 'Punishment roles:\n'
        for role_id in role_ids:
            try:
                role = get_role_from_id(self.bot, ctx.message.server, role_id)
                output += '\t' + role.name
            except Exception as e:
                output += str(e)

        await self.bot.say(box(output))

    @baduser.command(name="strikes", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def strikes(self, ctx, user : discord.Member):
        strikes = self.settings.countUserStrikes(ctx.message.server.id, user.id)
        await self.bot.say(box('User {} has {} strikes'.format(user.name, strikes)))

    async def mod_message(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return

        author = message.author
        content = message.clean_content
        channel = message.channel
        timestamp = str(message.timestamp)[:-7]
        log_msg = '[{}] {} ({}): {}/{}'.format(timestamp, author.name, author.id, channel.name, content)
        self.logs[author.id].append(log_msg)

    async def mod_ban(self, member):
        await self.recordBadUser(member, 'BANNED')

    async def mod_user_left(self, member):
        strikes = self.settings.countUserStrikes(member.server.id, member.id)
        if strikes:
            msg = 'FYI: A user with {} strikes just left the server: {}'.format(strikes, member.name)
            update_channel = self.settings.getChannel(member.server.id)
            if update_channel is not None:
                channel_obj = discord.Object(update_channel)
                await self.bot.send_message(channel_obj, msg)

    async def mod_user_join(self, member):
        strikes = self.settings.countUserStrikes(member.server.id, member.id)
        if strikes:
            msg = 'Hey @here a user with {} strikes just joined the server: {}'.format(strikes, member.name)
            update_channel = self.settings.getChannel(member.server.id)
            if update_channel is not None:
                channel_obj = discord.Object(update_channel)
                await self.bot.send_message(channel_obj, msg)

    async def check_punishment(self, before, after):
        if before.roles != after.roles:
            bad_role_ids = self.settings.getPunishmentRoles(after.server.id)
            for role in after.roles:
                if role.id in bad_role_ids:
                    await self.recordBadUser(after, role.name)
                    return

    async def recordBadUser(self, member, role_name):
        latest_messages = self.logs.get(member.id, "")
        msg = 'Name={} Nick={} ID={} Joined={} Role={}\n'.format(
           member.name, member.nick, member.id, member.joined_at, role_name)
        msg += '\n'.join(latest_messages)
        self.settings.updateBadUser(member.server.id, member.id, msg)
        strikes = self.settings.countUserStrikes(member.server.id, member.id)

        update_channel = self.settings.getChannel(member.server.id)
        if update_channel is not None:
            channel_obj = discord.Object(update_channel)
            await self.bot.send_message(channel_obj, inline('Detected bad user'))
            await self.bot.send_message(channel_obj, box(msg))
            await self.bot.send_message(channel_obj, 'Hey @here please leave a note explaining why this user is punished')
            await self.bot.send_message(channel_obj, 'This user now has {} strikes'.format(strikes))


def setup(bot):
    print('baduser bot setup')
    n = BadUser(bot)
    bot.add_listener(n.mod_message, "on_message")
    bot.add_listener(n.mod_ban, "on_member_ban")
    bot.add_listener(n.check_punishment, "on_member_update")
    bot.add_listener(n.mod_user_join, "on_member_join")
    bot.add_listener(n.mod_user_left, "on_member_remove")
    bot.add_cog(n)
    print('done adding baduser bot')


class BadUserSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'servers' : {}
        }
        return config

    def serverConfigs(self):
        return self.bot_settings['servers']

    def getServer(self, server_id):
        configs = self.serverConfigs()
        if server_id not in configs:
            configs[server_id] = {}
        return configs[server_id]

    def getBadUsers(self, server_id):
        server = self.getServer(server_id)
        if 'badusers' not in server:
            server['badusers'] = {}
        return server['badusers']

    def getPunishmentRoles(self, server_id):
        server = self.getServer(server_id)
        if 'role_ids' not in server:
            server['role_ids'] = []
        return server['role_ids']

    def addPunishmentRole(self, server_id, role_id):
        role_ids = self.getPunishmentRoles(server_id)
        if role_id not in role_ids:
            role_ids.append(role_id)
        self.save_settings()

    def rmPunishmentRole(self, server_id, role_id):
        role_ids = self.getPunishmentRoles(server_id)
        if role_id in role_ids:
            role_ids.remove(role_id)
        self.save_settings()

    def updateBadUser(self, server_id, user_id, msg):
        badusers = self.getBadUsers(server_id)
        if user_id not in badusers:
            badusers[user_id] = []

        badusers[user_id].append(msg)
        self.save_settings()

    def countUserStrikes(self, server_id, user_id):
        badusers = self.getBadUsers(server_id)
        if user_id not in badusers:
            return 0
        else:
            return len(badusers[user_id])

    def updateChannel(self, server_id, channel_id):
        server = self.getServer(server_id)
        if channel_id is None:
            if 'update_channel' in server:
                server.pop('update_channel')
                self.save_settings()
            return

        server['update_channel'] = channel_id
        self.save_settings()

    def getChannel(self, server_id):
        server = self.getServer(server_id)
        return server.get('update_channel')
