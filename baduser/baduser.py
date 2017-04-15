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
from .utils.chat_formatting import *
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
        """BadUser tools.

        The scope of this module has expanded a bit. It now covers both 'positive' and 'negative'
        roles. The goal is to assist coordination across moderators.

        When a user receives a negative role, a strike is automatically recorded for them. This
        captures their recent message history.

        You can specify a moderation channel for announcements. An announcement occurs on the
        following events:
        * User gains or loses a negative/positive role (includes a ping to @here)
        * User with a strike leaves the server
        * User with a strike joins the server (includes a ping to @here)

        Besides the automatic tracking, you can manually add strikes, print them, and clear them.
        """
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @baduser.command(name="addnegativerole", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addNegativeRole(self, ctx, *, role):
        """Designate a role as a 'punishment' role."""
        role = get_role(ctx.message.server.roles, role)
        self.settings.addPunishmentRole(ctx.message.server.id, role.id)
        await self.bot.say(inline('Added punishment role "' + role.name + '"'))

    @baduser.command(name="rmnegativerole", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmNegativeRole(self, ctx, *, role):
        """Cancels a role from 'punishment' status."""
        role = get_role(ctx.message.server.roles, role)
        self.settings.rmPunishmentRole(ctx.message.server.id, role.id)
        await self.bot.say(inline('Removed punishment role "' + role.name + '"'))

    @baduser.command(name="addpositiverole", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addPositiveRole(self, ctx, *, role):
        """Designate a role as a 'benefit' role."""
        role = get_role(ctx.message.server.roles, role)
        self.settings.addPositiveRole(ctx.message.server.id, role.id)
        await self.bot.say(inline('Added positive role "' + role.name + '"'))

    @baduser.command(name="rmpositiverole", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmPositiveRole(self, ctx, *, role):
        """Cancels a role from 'benefit' status."""
        role = get_role(ctx.message.server.roles, role)
        self.settings.rmPositiveRole(ctx.message.server.id, role.id)
        await self.bot.say(inline('Removed positive role "' + role.name + '"'))

    @baduser.command(name="setchannel", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def setChannel(self, ctx, channel: discord.Channel):
        """Set the channel for moderation announcements."""
        self.settings.updateChannel(ctx.message.server.id, channel.id)
        await self.bot.say(inline('Set the announcement channel'))

    @baduser.command(name="clearchannel", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def clearChannel(self, ctx):
        """Clear the channel for moderation announcements."""
        self.settings.updateChannel(ctx.message.server.id, None)
        await self.bot.say(inline('Cleared the announcement channel'))

    @baduser.command(name="list", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def list(self, ctx):
        """List the positive/negative role configuration."""
        output = 'Punishment roles:\n'
        for role_id in self.settings.getPunishmentRoles(ctx.message.server.id):
            try:
                role = get_role_from_id(self.bot, ctx.message.server, role_id)
                output += '\t' + role.name
            except Exception as e:
                output += str(e)
        output += '\nPositive roles:\n'
        for role_id in self.settings.getPositiveRoles(ctx.message.server.id):
            try:
                role = get_role_from_id(self.bot, ctx.message.server, role_id)
                output += '\t' + role.name
            except Exception as e:
                output += str(e)

        await self.bot.say(box(output))

    @baduser.command(name="strikes", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def strikes(self, ctx, user : discord.Member):
        """Print the strike count for a user."""
        strikes = self.settings.countUserStrikes(ctx.message.server.id, user.id)
        await self.bot.say(box('User {} has {} strikes'.format(user.name, strikes)))

    @baduser.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addstrike(self, ctx, user : discord.Member, *, strike_text : str):
        """Manually add a strike to a user."""
        timestamp = str(ctx.message.timestamp)[:-7]
        msg = 'Manually added by {} ({}): {}'.format(ctx.message.author.name, timestamp, strike_text)
        self.settings.updateBadUser(user.server.id, user.id, msg)
        strikes = self.settings.countUserStrikes(ctx.message.server.id, user.id)
        await self.bot.say(box('Done. User {} now has {} strikes'.format(user.name, strikes)))

    @baduser.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def clearstrikes(self, ctx, user : discord.Member):
        """Clear all strikes for a user."""
        self.settings.clearUserStrikes(ctx.message.server.id, user.id)
        await self.bot.say(box('Cleared strikes for {}'.format(user.name)))

    @baduser.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def printstrikes(self, ctx, user : discord.Member):
        """Print all strikes for a user."""
        strikes = self.settings.getUserStrikes(ctx.message.server.id, user.id)
        if not strikes:
            await self.bot.say(box('No strikes for {}'.format(user.name)))
            return

        for idx, strike in enumerate(strikes):
            await self.bot.say(inline('Strike {} of {}:'.format(idx + 1, len(strikes))))
            await self.bot.say(box(strike))

    @baduser.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def report(self, ctx):
        """Displays a report of information on bad users for the server."""
        cur_server = ctx.message.server

        user_id_to_ban_server = defaultdict(list)
        user_id_to_baduser_server = defaultdict(list)
        error_messages = list()
        for server in self.bot.servers:
            if server.id == cur_server.id:
                continue

            try:
                ban_list = await self.bot.get_bans(server)
            except:
                ban_list = list()
                error_messages.append("Server '{}' refused access to ban list".format(server.name))

            for user in ban_list:
                user_id_to_ban_server[user.id].append(server.id)

            baduser_list = self.settings.getBadUsers(server.id)
            for user_id in baduser_list:
                user_id_to_baduser_server[user_id].append(server.id)

        bad_users = self.settings.getBadUsers(cur_server.id)

        baduser_entries = list()
        otheruser_entries = list()

        await self.bot.request_offline_members(server)
        for member in server.members:
            local_strikes = self.settings.getUserStrikes(server.id, member.id)
            other_baduser_servers = user_id_to_baduser_server[member.id]
            other_banned_servers = user_id_to_ban_server[member.id]

            if not len(local_strikes) and not len(other_baduser_servers) and not len(other_banned_servers):
                continue

            tmp_msg = "{} ({})".format(member.name, member.id)
            tmp_msg += "\n\tbad user in {} other servers".format(len(other_baduser_servers))
            tmp_msg += "\n\tbanned from {} other servers".format(len(other_banned_servers))

            if len(local_strikes):
                tmp_msg += "\n\t{} strikes in this server".format(len(local_strikes))
                for strike in local_strikes:
                    tmp_msg += "\n\t\t{}".format(strike.splitlines()[0])
                baduser_entries.append(tmp_msg)
            else:
                otheruser_entries.append(tmp_msg)


        other_server_count = len(self.bot.servers) - 1
        other_ban_count = len([x for x, l in user_id_to_ban_server.items() if len(l)])
        other_baduser_count = len([x for x, l in user_id_to_baduser_server.items() if len(l)])
        msg = "Across {} other servers, {} users are banned and {} have baduser entries".format(
                other_server_count, other_ban_count, other_baduser_count)

        msg += "\n\n{} baduser entries for this server".format(len(baduser_entries))
        msg += "\n" + "\n".join(baduser_entries)
        msg += "\n\n{} entries for users with no record in this server".format(len(otheruser_entries))
        msg += "\n" + "\n".join(otheruser_entries)

        if error_messages:
            msg += "\n\nSome errors occurred:"
            msg += "\n" + "\n".join(error_messages)

        for page in pagify(msg):
            await self.bot.say(box(page))

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
        if before.roles == after.roles:
            return

        new_roles = set(after.roles).difference(before.roles)
        removed_roles = set(before.roles).difference(after.roles)

        bad_role_ids = self.settings.getPunishmentRoles(after.server.id)
        positive_role_ids = self.settings.getPositiveRoles(after.server.id)

        for role in new_roles:
            if role.id in bad_role_ids:
                await self.recordBadUser(after, role.name)
                return

            if role.id in positive_role_ids:
                await self.recordRoleChange(after, role.name, True)
                return

        for role in removed_roles:
            if role.id in positive_role_ids:
                await self.recordRoleChange(after, role.name, False)
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

            try:
                dm_msg = ('You were assigned the punishment role "{}" in the server "{}".\n'
                         'The Mods will contact you shortly regarding this.\n'
                         'Attempting to clear this role yourself will result in punishment.').format(role_name, member.server.name)
                await self.bot.send_message(member, box(dm_msg))
                await self.bot.send_message(channel_obj, 'User successfully notified')
            except Exception as e:
                await self.bot.send_message(channel_obj, 'Failed to notify the user! I might be blocked\n' + box(str(e)))

    async def recordRoleChange(self, member, role_name, is_added):
        msg = 'Detected role {} : Name={} Nick={} ID={} Joined={} Role={}'.format(
           "Added" if is_added else "Removed", member.name, member.nick, member.id, member.joined_at, role_name)

        update_channel = self.settings.getChannel(member.server.id)
        if update_channel is not None:
            channel_obj = discord.Object(update_channel)
            try:
                await self.bot.send_message(channel_obj, inline(msg))
                await self.bot.send_message(channel_obj, 'Hey @here please leave a note explaining why this role was modified')
            except:
                print('Failed to notify in', update_channel, msg)


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

    def getPositiveRoles(self, server_id):
        server = self.getServer(server_id)
        if 'positive_role_ids' not in server:
            server['positive_role_ids'] = []
        return server['positive_role_ids']

    def addPositiveRole(self, server_id, role_id):
        role_ids = self.getPositiveRoles(server_id)
        if role_id not in role_ids:
            role_ids.append(role_id)
        self.save_settings()

    def rmPositiveRole(self, server_id, role_id):
        role_ids = self.getPositiveRoles(server_id)
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

    def clearUserStrikes(self, server_id, user_id):
        badusers = self.getBadUsers(server_id)
        badusers.pop(user_id, None)
        self.save_settings()

    def getUserStrikes(self, server_id, user_id):
        badusers = self.getBadUsers(server_id)
        return badusers.get(user_id, [])

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
