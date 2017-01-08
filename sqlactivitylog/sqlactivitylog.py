from datetime import datetime
import os

import discord
from discord.ext import commands

from __main__ import send_cmd_help
from cogs.utils import checks
from cogs.utils.dataIO import dataIO
import sqlite3 as lite

from .utils.chat_formatting import *


TIMESTAMP_FORMAT = '%Y-%m-%d %X'  # YYYY-MM-DD HH:MM:SS
PATH_LIST = ['data', 'sqlactivitylog']
PATH = os.path.join(*PATH_LIST)
JSON = os.path.join(*PATH_LIST, "settings.json")
DB = os.path.join(*PATH_LIST, "log.db")


CREATE_TABLE = '''
CREATE TABLE IF NOT EXISTS messages(
  rowid INTEGER PRIMARY KEY ASC AUTOINCREMENT,
  timestamp TIMESTAMP NOT NULL,
  server_id STRING NOT NULL,
  channel_id STRING NOT NULL,
  user_id STRING NOT NULL,
  msg_type STRING NOT NULL,
  content STRING NOT NULL,
  clean_content STRING NOT NULL)
'''


class SqlActivityLogger(object):
    """Log activity seen by bot"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(JSON)
        self.lock = False
        self.con = lite.connect(DB)
        self.con.execute(CREATE_TABLE)

    def __unload(self):
        self.lock = True
        self.con.close()

    @commands.group(pass_context=True)
    @checks.is_owner()
    async def sqllog(self, ctx):
        """Supports SQL queries for messages viewed by the bot"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @commands.command(pass_context=True)
    @checks.is_owner()
    async def rawquery(self, ctx, *, query : str):
        result_text = ""
        cursor = self.con.execute(query)
        rows = cursor.fetchall()
        result_text = "{} rows in result".format(len(rows))
        for idx, row in enumerate(rows):
            if idx >= 1000:
                break
            result_text += "\n" + str(row)
        for p in pagify(result_text):
            await self.bot.say(box(p))


    def save_json(self):
        dataIO.save_json(JSON, self.settings)


    async def on_message(self, message):
        self.log('NEW', message)

    async def on_message_edit(self, before, after):
        self.log('EDIT', after)

    async def on_message_delete(self, message):
        self.log('DELETE', message)

    def log(self, msg_type, message):
        if self.lock:
            print('aborting log: db locked')
            return
        stmt = '''
          INSERT INTO messages(timestamp, server_id, channel_id, user_id, msg_type, content, clean_content)
          VALUES(:timestamp, :server_id, :channel_id, :user_id, :msg_type, :content, :clean_content)
        '''
        timestamp = 0
        server_id = message.server.id if message.server else -1
        channel_id = message.channel.id if message.channel else -1
        values = {
          'timestamp': message.timestamp,
          'server_id': server_id,
          'channel_id': channel_id,
          'user_id': message.author.id,
          'msg_type': msg_type,
          'content': message.content,
          'clean_content': message.clean_content,
        }
        self.con.execute(stmt, values)
        self.con.commit()


def check_folders():
    if not os.path.exists(PATH):
        os.mkdir(PATH)


def check_files():
    if not dataIO.is_valid_json(JSON):
        defaults = {}
        dataIO.save_json(JSON, defaults)


def setup(bot):
    check_folders()
    check_files()
    n = SqlActivityLogger(bot)
    bot.add_cog(n)
