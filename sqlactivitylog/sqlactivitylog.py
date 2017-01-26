from datetime import datetime
import os

import discord
from discord.ext import commands
import prettytable
import pytz

from __main__ import send_cmd_help
from cogs.utils import checks
from cogs.utils.dataIO import dataIO
import sqlite3 as lite

from .rpadutils import *
from .utils.chat_formatting import *


TIMESTAMP_FORMAT = '%Y-%m-%d %X'  # YYYY-MM-DD HH:MM:SS
PATH_LIST = ['data', 'sqlactivitylog']
PATH = os.path.join(*PATH_LIST)
JSON = os.path.join(*PATH_LIST, "settings.json")
DB = os.path.join(*PATH_LIST, "log.db")

ALL_COLUMNS = [
          ('timestamp', 'Time (PT)'),
          ('server_id', 'Server'),
          ('channel_id', 'Channel'),
          ('user_id', 'User'),
          ('msg_type', 'Type'),
          ('clean_content', 'Message'),
]

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

MAX_LOGS = 500

USER_QUERY = '''
SELECT timestamp, channel_id, msg_type, clean_content
FROM messages
WHERE server_id = :server_id
  AND user_id = :user_id
ORDER BY timestamp DESC
LIMIT :row_count
'''

CHANNEL_QUERY = '''
SELECT timestamp, user_id, msg_type, clean_content
FROM messages
WHERE server_id = :server_id
  AND channel_id = :channel_id
  AND user_id <> :bot_id
ORDER BY timestamp DESC
LIMIT :row_count
'''

USER_CHANNEL_QUERY = '''
SELECT timestamp, msg_type, clean_content
FROM messages
WHERE server_id = :server_id
  AND user_id = :user_id
  AND channel_id = :channel_id
ORDER BY timestamp DESC
LIMIT :row_count
'''

CONTENT_QUERY = '''
SELECT timestamp, channel_id, user_id, msg_type, clean_content
FROM messages
WHERE server_id = :server_id
  AND lower(clean_content) LIKE lower(:content_query)
  AND user_id <> :bot_id
ORDER BY timestamp DESC
LIMIT :row_count
'''


class SqlActivityLogger(object):
    """Log activity seen by bot"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(JSON)
        self.lock = False
        self.con = lite.connect(DB, detect_types=lite.PARSE_DECLTYPES)
        self.con.row_factory = lite.Row
        self.con.execute(CREATE_TABLE)

    def __unload(self):
        self.lock = True
        self.con.close()

    @commands.command(pass_context=True)
    @checks.is_owner()
    async def rawquery(self, ctx, *, query : str):
        await self.queryAndPrint(ctx.message.server, query, {}, {})

    @commands.group(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def exlog(self, context):
        """Extra log querying tools.

        Uses the bot's local SQL message storage to retrieve messages
        seen in the current server since the cog was installed.
        """
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @exlog.command(pass_context=True, no_pm=True)
    async def user(self, ctx, user : discord.Member, count=10):
        """exlog user tactical_retreat 100

        List of messages for a user across all channels.
        Count is optional, with a low default and a maximum value.
        """
        count = min(count, MAX_LOGS)
        server = ctx.message.server
        values = {
          'server_id': server.id,
          'row_count': count,
          'user_id': user.id,
        }
        column_data = [
          ('timestamp', 'Time (PT)'),
          ('channel_id', 'Channel'),
          ('msg_type', 'Type'),
          ('clean_content', 'Message'),
        ]

        await self.queryAndPrint(server, USER_QUERY, values, column_data)

    @exlog.command(pass_context=True, no_pm=True)
    async def channel(self, ctx, channel : discord.Channel, count=10):
        """exlog channel #general_chat 100

        List of messages in a given channel.
        Count is optional, with a low default and a maximum value.
        The bot is excluded from results.
        """
        count = min(count, MAX_LOGS)
        server = ctx.message.server
        values = {
          'server_id': server.id,
          'bot_id': self.bot.user.id,
          'row_count': count,
          'channel_id': channel.id,
        }
        column_data = [
          ('timestamp', 'Time (PT)'),
          ('user_id', 'User'),
          ('msg_type', 'Type'),
          ('clean_content', 'Message'),
        ]

        await self.queryAndPrint(server, CHANNEL_QUERY, values, column_data)

    @exlog.command(pass_context=True, no_pm=True)
    async def userchannel(self, ctx, user : discord.Member, channel : discord.Channel, count=10):
        """exlog userchannel tactical_retreat #general_chat 100

        List of messages from a user in a given channel.
        Count is optional, with a low default and a maximum value.
        """
        count = min(count, MAX_LOGS)
        server = ctx.message.server
        values = {
          'server_id': server.id,
          'row_count': count,
          'channel_id': channel.id,
          'user_id': user.id,
        }
        column_data = [
          ('timestamp', 'Time (PT)'),
          ('msg_type', 'Type'),
          ('clean_content', 'Message'),
        ]

        await self.queryAndPrint(server, USER_CHANNEL_QUERY, values, column_data)

    @exlog.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def query(self, ctx, query, count=10):
        """exlog query "4 whale" 100

        Case-insensitive search of messages from every user/channel.
        Put the query in quotes if it is more than one word.
        Count is optional, with a low default and a maximum value.
        The bot is excluded from results.
        """
        count = min(count, MAX_LOGS)
        server = ctx.message.server
        values = {
          'server_id': server.id,
          'bot_id': self.bot.user.id,
          'row_count': count,
          'content_query': query,
        }
        column_data = [
          ('timestamp', 'Time (PT)'),
          ('channel_id', 'Channel'),
          ('user_id', 'User'),
          ('msg_type', 'Type'),
          ('clean_content', 'Message'),
        ]

        await self.queryAndPrint(server, CONTENT_QUERY, values, column_data)

    async def queryAndPrint(self, server, query, values, column_data, max_rows=MAX_LOGS * 2):
        cursor = self.con.execute(query, values)
        rows = cursor.fetchall()

        if len(column_data) == 0:
            column_data = ALL_COLUMNS

        column_names = [c[0] for c in column_data]
        column_headers = [c[1] for c in column_data]

        tbl = prettytable.PrettyTable(column_headers)
        tbl.hrules = prettytable.HEADER
        tbl.vrules = prettytable.NONE
        tbl.align = 'l'

        for idx, row in enumerate(rows):
            if idx > max_rows:
                break;

            table_row = list()
            for col in column_names:
                if col not in row.keys():
                    table_row.append('')
                    continue
                raw_value = row[col]
                value = str(raw_value)
                if col == 'timestamp':
                    # Assign a UTC timezone to the datetime
                    raw_value = raw_value.replace(tzinfo=pytz.utc)
                    # Change the UTC timezone to PT
                    raw_value = NA_TZ_OBJ.normalize(raw_value)
                    value = raw_value.strftime("%F %X")
                if col == 'channel_id':
                    channel = server.get_channel(value)
                    value = channel.name if channel else value
                if col == 'user_id':
                    member = server.get_member(value)
                    value = member.name if member else value
                if col == 'server_id':
                    server_obj = self.bot.get_server(value)
                    value = server_obj.name if server_obj else value
                if col == 'clean_content':
                    value = value.replace('`', '\`')
                table_row.append(value)

            tbl.add_row(table_row)

        result_text = "{} results\n{}".format(len(rows), tbl.get_string())
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
