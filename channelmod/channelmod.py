from _datetime import datetime
import asyncio
import logging
import os
import traceback

import discord
from discord.ext import commands

from cogs.utils import checks
from cogs.utils.chat_formatting import inline, box

from .utils.cog_settings import *


log = logging.getLogger("red.admin")

INACTIVE = '_inactive'


class ChannelMod:
    """Channel moderation tools."""

    def __init__(self, bot):
        self.bot = bot
        self.settings = ChannelModSettings("channelmod")

    @commands.group(pass_context=True, no_pm=True)
    async def channelmod(self, ctx):
        """Manage Channel Moderation settings"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @channelmod.command(pass_context=True)
    @checks.mod_or_permissions(manage_channels=True)
    async def inactivemonitor(self, ctx, timeout: int):
        """Enable/disable the activity monitor on this channel.

        Timeout is in seconds. Set to 0 to disable.

        Set the timeout >0 to have the bot automatically append '_inactive' to the channel
        name when the oldest message in the channel is greater than the timeout.
        """
        channel = ctx.message.channel
        server = channel.server
        has_permissions = channel.permissions_for(server.me).manage_channels
        if not has_permissions:
            await self.bot.say(inline('I need manage channel permissions to do this'))
            return

        self.settings.set_inactivity_monitor_channel(server.id, channel.id, timeout)
        await self.bot.say(inline('done'))

    async def log_channel_activity_check(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return

        server = message.server
        channel = message.channel
        timeout = self.settings.get_inactivity_monitor_channel_timeout(server.id, channel.id)

        if timeout > 0 and channel.name.endswith(INACTIVE):
            new_name = channel.name[:-len(INACTIVE)]
            await self.bot.edit_channel(channel, name=new_name)

    async def check_inactive_channel(self, server_id: str, channel_id: str, timeout: int):
        try:
            channel = self.bot.get_channel(channel_id)
            server = channel.server
            if channel is None:
                print('cannot find channel, disabling', channel_id)
                self.settings.set_inactivity_monitor_channel(server_id, channel_id, 0)
                return

            has_permissions = channel.permissions_for(server.me).manage_channels
            if not has_permissions:
                print('no manage channel permissions, disabling', channel_id)
                self.settings.set_inactivity_monitor_channel(server_id, channel_id, 0)
                return

            async for message in self.bot.logs_from(channel, limit=1):
                pass

            time_delta = datetime.utcnow() - message.timestamp
            time_exceeded = time_delta.total_seconds() > timeout

            if time_exceeded and not channel.name.endswith(INACTIVE):
                new_name = channel.name + INACTIVE
                await self.bot.edit_channel(channel, name=new_name)

        except Exception as ex:
            print('failed to check inactivity channel')
            traceback.print_exc()
#             self.settings.set_inactivity_monitor_channel(server_id, channel_id, 0)

    async def check_inactive_channels(self):
        for server_id in self.settings.servers().keys():
            for channel_id, channel_config in self.settings.get_inactivity_monitor_channels(server_id).items():
                timeout = channel_config['timeout']
                if timeout > 0:
                    await self.check_inactive_channel(server_id, channel_id, timeout)

    async def channel_inactivity_monitor(self):
        while self == self.bot.get_cog('ChannelMod'):
            await self.check_inactive_channels()
            await asyncio.sleep(20)


def setup(bot):
    n = ChannelMod(bot)
    bot.add_cog(n)
    bot.add_listener(n.log_channel_activity_check, "on_message")
    bot.loop.create_task(n.channel_inactivity_monitor())


class ChannelModSettings(CogSettings):
    def make_default_settings(self):
        config = {
            'servers': {},
        }
        return config

    def servers(self):
        return self.bot_settings['servers']

    def get_server(self, server_id: str):
        servers = self.servers()
        if server_id not in servers:
            servers[server_id] = {}
        return servers[server_id]

    def get_inactivity_monitor_channels(self, server_id: str):
        server = self.get_server(server_id)
        key = 'inactivity_monitor_channels'
        if key not in server:
            server[key] = {}
        return server[key]

    def set_inactivity_monitor_channel(self, server_id: str, channel_id: str, timeout: int):
        channels = self.get_inactivity_monitor_channels(server_id)
        channels[channel_id] = {'timeout': timeout}
        self.save_settings()

    def get_inactivity_monitor_channel_timeout(self, server_id: str, channel_id: str):
        channels = self.get_inactivity_monitor_channels(server_id)
        channel = channels.get(channel_id, {})
        return channel.get('timeout', 0)
