import discord
from .utils import checks
from discord.ext import commands
from .utils.dataIO import fileIO
from __main__ import send_cmd_help
from time import time
import os

from collections import deque
from collections import defaultdict
import copy

LOGS_PER_CHANNEL = 1000

class AdminLog:
    def __init__(self, bot):
        self.bot = bot
        self.file = 'data/adminlog/{}.log'
        self.ignore_file = 'data/adminlog/adminlog.json'
        
        self.logs = defaultdict(lambda: deque(maxlen=LOGS_PER_CHANNEL))

    @commands.group(pass_context=True, no_pm=True, name='adminlogs', aliases=['adminlog'])
    async def _adminlogs(self, context):
        """Admin log tools."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    async def log_message(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return
        
        author = message.author
        content = message.clean_content
        timestamp = str(message.timestamp)[:-7]
        log_msg = '[{}] (NEW) {} ({}): {}'.format(timestamp, author.name, author.id, content)
        self.logs[message.channel.id].append(log_msg)

    async def log_message_delete(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return
        
        author = message.author
        content = message.clean_content
        timestamp = str(message.timestamp)[:-7]
        log_msg = '[{}] (DEL) {} ({}): {}'.format(timestamp, author.name, author.id, content)
        self.logs[message.channel.id].append(log_msg)

    async def log_message_edit(self, before, after):
        if before.author.id == self.bot.user.id or before.channel.is_private:
            return
        
        author = before.author
        content_old = before.clean_content
        content_new = after.clean_content
        timestamp = str(after.timestamp)[:-7]
        log_msg = '[{}] (EDT) {} ({}): {} -> {}'.format(timestamp, author.name, author.id, content_old, content_new)
        self.logs[before.channel.id].append(log_msg)
        
        
    @_adminlogs.command(pass_context=True, no_pm=True, name='all')
    @checks.mod_or_permissions(manage_channels=True)
    async def _get(self, context, channel: discord.Channel):
        """[channel]"""
        data = fileIO(self.ignore_file, "load")
        current_server = context.message.server.id
        current_channel = channel.id
        if current_server not in data:
            data[current_server] = []
        if current_channel not in data[current_server]:
            log = []
            try:
                for message in self.logs[channel.id]:
                    log.append(message)
                try:
                    t = self.file.format(str(time()).split('.')[0])
                    with open(t, encoding='utf-8', mode="w") as f:
                        for message in log[::-1]:
                            f.write(message+'\n')
                    f.close()
                    await self.bot.send_file(context.message.channel, t)
                    os.remove(t)
                except Exception as error:
                    print(error)
            except discord.errors.Forbidden:
                await self.bot.say('I don\'t have permission!')
 
def check_folder():
    if not os.path.exists("data/adminlog"):
        print("Creating data/adminlog folder...")
        os.makedirs("data/adminlog")

def check_file():
    data = {}
    f = "data/adminlog/adminlog.json"
    if not fileIO(f, "check"):
        print("Creating default adminlog.json...")
        fileIO(f, "save", data)

def setup(bot):
    check_folder()
    check_file()
    n = AdminLog(bot)
    bot.add_listener(n.log_message, "on_message")
    bot.add_listener(n.log_message_delete, "on_message_delete")
    bot.add_listener(n.log_message_edit, "on_message_edit")
    bot.add_cog(n)
