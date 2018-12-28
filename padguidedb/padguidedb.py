from datetime import time
import json

import discord
from discord.ext import commands
import prettytable
import pymysql

from __main__ import user_allowed, send_cmd_help

from . import rpadutils
from .rpadutils import *
from .rpadutils import CogSettings
from .utils import checks
from .utils.dataIO import dataIO


PADGUIDEDB_COG = None


def is_padguidedb_admin_check(ctx):
    is_owner = PADGUIDEDB_COG.bot.settings.owner == ctx.message.author.id
    return is_owner or PADGUIDEDB_COG.settings.checkAdmin(ctx.message.author.id)


def is_padguidedb_admin():
    return commands.check(is_padguidedb_admin_check)


class PadGuideDb:
    """PadGuide Database manipulator"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = PadGuideDbSettings("padguidedb")

        global PADGUIDEDB_COG
        PADGUIDEDB_COG = self

    def get_connection(self):
        with open(self.settings.configFile()) as f:
            db_config = json.load(f)
        return self.connect(db_config)

    def connect(self, db_config):
        return pymysql.connect(host=db_config['host'],
                               user=db_config['user'],
                               password=db_config['password'],
                               db=db_config['db'],
                               charset=db_config['charset'],
                               cursorclass=pymysql.cursors.DictCursor,
                               autocommit=True)

    @commands.group(pass_context=True)
    @is_padguidedb_admin()
    async def padguidedb(self, context):
        """PadGuide database manipulation."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @padguidedb.command(pass_context=True)
    @checks.is_owner()
    async def addadmin(self, ctx, user: discord.Member):
        """Adds a user to the padguide db admin"""
        self.settings.addAdmin(user.id)
        await self.bot.say("done")

    @padguidedb.command(pass_context=True)
    @checks.is_owner()
    async def rmadmin(self, ctx, user: discord.Member):
        """Removes a user from the padguide db admin"""
        self.settings.rmAdmin(user.id)
        await self.bot.say("done")

    @padguidedb.command(pass_context=True)
    @checks.is_owner()
    async def setconfigfile(self, ctx, *, config_file):
        """Set the database config file."""
        self.settings.setConfigFile(config_file)
        await self.bot.say(inline('Done'))

    @padguidedb.command(pass_context=True)
    @is_padguidedb_admin()
    async def dungeonstub(self, ctx, *, pad_dungeon_id: int):
        """Creates a stub entry for a dungeon"""
        sql_items = []
        with self.get_connection() as cursor:
            sql = 'select * from etl_dungeon_map where pad_dungeon_id={}'.format(pad_dungeon_id)
            cursor.execute(sql)
            results = list(cursor.fetchall())
            if results:
                await self.bot.say(inline('found an existing mapping for that dungeon'))
                return

            def load_dungeon(file_path):
                with open(file_path) as f:
                    data = json.load(f)
                    for d in data:
                        if d['dungeon_id'] == pad_dungeon_id:
                            return d
                    return None

            jp_entry = load_dungeon('/home/tactical0retreat/pad_data/processed/jp_dungeons.json')
            na_entry = load_dungeon(
                '/home/tactical0retreat/pad_data/processed/na_dungeons.json') or jp_entry

            jp_name = jp_entry['clean_name']
            en_name = na_entry['clean_name']

            tstamp = int(time.time()) * 1000
            sql = ('insert into dungeon_list (dungeon_type, icon_seq, name_jp, name_kr, name_us, order_idx, show_yn, tdt_seq, tstamp)'
                   " values (1, 0, '{}', '{}', '{}', 0, 1, 41, {})".format(jp_name, en_name, en_name, tstamp))
            sql_items.append(sql)
            cursor.execute(sql)
            dungeon_seq = cursor.lastrowid

            sql = 'delete from etl_dungeon_ignore where pad_dungeon_id={}'.format(pad_dungeon_id)
            sql_items.append(sql)
            cursor.execute(sql)
            sql = 'insert into etl_dungeon_map (pad_dungeon_id, dungeon_seq) values ({}, {})'.format(
                pad_dungeon_id, dungeon_seq)
            sql_items.append(sql)
            cursor.execute(sql)

            await self.bot.say(box('Finished running:\n' + '\n'.join(sql_items)))

    @padguidedb.command(pass_context=True)
    @is_padguidedb_admin()
    async def searchdungeon(self, ctx, *, search_text):
        """Search"""
        search_text = search_text.replace("@#$%^&*;/<>?\|`~-=", " ")
        with self.get_connection() as cursor:
            sql = ("select dungeon_seq, name_us, name_jp from dungeon_list"
                   " where (lower(name_us) like '%{}%' or lower(name_jp) like '%{}%')"
                   " and show_yn = 1"
                   " order by dungeon_seq limit 20".format(search_text, search_text))
            cursor.execute(sql)
            results = list(cursor.fetchall())
            msg = 'Results\n' + json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False)
            await self.bot.say(inline(sql))
            for page in pagify(msg):
                await self.bot.say(box(page))

    @padguidedb.command(pass_context=True)
    @is_padguidedb_admin()
    async def mapdungeon(self, ctx, pad_dungeon_id: int, dungeon_seq: int):
        """Map dungeon"""
        with self.get_connection() as cursor:
            sql = 'select * from etl_dungeon_ignore where pad_dungeon_id={}'.format(pad_dungeon_id)
            cursor.execute(sql)
            ignore_results = len(cursor.fetchall())
            msg = 'pad_dungeon_id {} {} currently ignored'.format(
                pad_dungeon_id, 'is' if ignore_results else 'is not')
            await self.bot.say(inline(msg))

            sql = 'select * from etl_dungeon_map where pad_dungeon_id={} and dungeon_seq={}'.format(
                pad_dungeon_id, dungeon_seq)
            cursor.execute(sql)
            mapping_results = list(cursor.fetchall())
            if len(mapping_results):
                await self.bot.say(inline('that mapping already exists, exiting'))
                return

            sql = 'select * from etl_dungeon_map where pad_dungeon_id={} or dungeon_seq={}'.format(
                pad_dungeon_id, dungeon_seq)
            cursor.execute(sql)
            mapping_results = list(cursor.fetchall())
            msg = 'Existing mappings\n' + json.dumps(mapping_results, indent=2, sort_keys=True)
            for page in pagify(msg):
                await self.bot.say(box(page))

            sql_items = []
            if ignore_results:
                sql_items.append(
                    'delete from etl_dungeon_ignore where pad_dungeon_id={}'.format(pad_dungeon_id))
            sql_items.append('insert into etl_dungeon_map (pad_dungeon_id, dungeon_seq) values ({}, {})'.format(
                pad_dungeon_id, dungeon_seq))

            await self.bot.say(box('I will apply these updates:\n' + '\n'.join(sql_items)))

            await self.bot.say(inline('type yes to apply updates'))
            msg = await self.bot.wait_for_message(timeout=30, author=ctx.message.author)
            if not msg or msg.content[0].lower() != 'y':
                await self.bot.say(inline('aborting'))
                return

            for sql in sql_items:
                await self.bot.say(inline('running: ' + sql))
                cursor.execute(sql)


def setup(bot):
    n = PadGuideDb(bot)
    bot.add_cog(n)


class PadGuideDbSettings(CogSettings):
    def make_default_settings(self):
        config = {
            'admins': [],
            'config_file': '',
        }
        return config

    def admins(self):
        return self.bot_settings['admins']

    def checkAdmin(self, user_id):
        admins = self.admins()
        return user_id in admins

    def addAdmin(self, user_id):
        admins = self.admins()
        if user_id not in admins:
            admins.append(user_id)
            self.save_settings()

    def rmAdmin(self, user_id):
        admins = self.admins()
        if user_id in admins:
            admins.remove(user_id)
            self.save_settings()

    def configFile(self):
        return self.bot_settings.get('config_file', '')

    def setConfigFile(self, config_file):
        self.bot_settings['config_file'] = config_file
        self.save_settings()
