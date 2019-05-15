"""
Provides access to PadGuide data.

Loads every PadGuide related JSON into a simple data structure, and then
combines them into a an in-memory interconnected database.

Don't hold on to any of the dastructures exported from here, or the
entire database could be leaked when the module is reloaded.
"""
from _collections import defaultdict
import asyncio
import csv
from datetime import datetime
from datetime import timedelta
import difflib
from itertools import groupby
import json
from operator import itemgetter
import os
import re
import time
import traceback

import aiohttp
import discord
from discord.ext import commands
from enum import Enum
import pytz
import romkan

from __main__ import send_cmd_help

from . import rpadutils
from .rpadutils import CogSettings
from .utils import checks
from .utils.chat_formatting import box, inline
from .utils.dataIO import dataIO


DUMMY_FILE_PATTERN = 'data/padguide2/{}.dummy'
JSON_FILE_PATTERN = 'data/padguide2/{}.json'
CSV_FILE_PATTERN = 'data/padguide2/{}.csv'
ATTR_EXPORT_PATH = 'data/padguide2/card_data.csv'
NAMES_EXPORT_PATH = 'data/padguide2/computed_names.json'
BASENAMES_EXPORT_PATH = 'data/padguide2/base_names.json'
TRANSLATEDNAMES_EXPORT_PATH = 'data/padguide2/translated_names.json'

SHEETS_PATTERN = 'https://docs.google.com/spreadsheets/d/1EoZJ3w5xsXZ67kmarLE4vfrZSIIIAfj04HXeZVST3eY/pub?gid={}&single=true&output=csv'
GROUP_BASENAMES_OVERRIDES_SHEET = SHEETS_PATTERN.format('2070615818')
NICKNAME_OVERRIDES_SHEET = SHEETS_PATTERN.format('0')
PANTHNAME_OVERRIDES_SHEET = SHEETS_PATTERN.format('959933643')

NICKNAME_FILE_PATTERN = CSV_FILE_PATTERN.format('nicknames')
BASENAME_FILE_PATTERN = CSV_FILE_PATTERN.format('basenames')
PANTHNAME_FILE_PATTERN = CSV_FILE_PATTERN.format('panthnames')


class PadGuide2(object):
    def __init__(self, bot):
        self.bot = bot
        self._is_ready = asyncio.Event(loop=self.bot.loop)

        self.settings = PadGuide2Settings("padguide2")
        self.reload_task = None

        self._standard_refresh = [
            PgAttribute,
            PgAwakening,
            PgDungeon,
            # PgDungeonDamage,
            PgDungeonMonsterDrop,
            PgDungeonMonster,
            # PgDungeonSkill,
            # PgDungeonType,
            PgEggInstance,
            PgEggMonster,
            PgEggName,
            PgEvent,
            PgEvolution,
            PgEvolutionMaterial,
            PgMonster,
            PgMonsterAddInfo,
            PgMonsterInfo,
            PgMonsterPrice,
            PgSeries,
            PgSkillLeaderData,
            PgSkill,
            PgSkillRotation,
            PgSkillRotationDated,
            # PgSubDungeon,
            PgType,
        ]

        self._quick_refresh = [
            PgScheduledEvent,
        ]

        # A string -> int mapping, nicknames to monster_id_na
        self.nickname_overrides = {}

        # An int -> set(string), monster_id_na to set of basename overrides
        self.basename_overrides = defaultdict(set)
        
        self.panthname_overrides = defaultdict(set)

        self.database = PgRawDatabase(skip_load=True)

        # Map of google-translated JP names to EN names
        self.translated_names = {}

    @asyncio.coroutine
    def wait_until_ready(self):
        """Wait until the PadGuide2 cog is ready.

        Call this from other cogs to wait until PadGuide2 finishes refreshing its database
        for the first time.
        """
        yield from self._is_ready.wait()

    def create_index(self, accept_filter=None):
        """Exported function that allows a client cog to create a monster index"""
        return MonsterIndex(self.database, self.nickname_overrides, self.basename_overrides, self.panthname_overrides, accept_filter=accept_filter)

    def get_monster_by_no(self, monster_no: int):
        """Exported function that allows a client cog to get a full PgMonster by monster_no"""
        return self.database.getMonster(monster_no)

    def get_translated_jp_name(self, jp_name):
        return self.translate_names.get(jp_name, None)

    def register_tasks(self):
        self.reload_task = self.bot.loop.create_task(self.reload_data_task())

    def __unload(self):
        # Manually nulling out database because the GC for cogs seems to be pretty shitty
        self.database = None
        self._is_ready.clear()

    async def reload_data_task(self):
        await self.bot.wait_until_ready()

        try:
            # Try and load the PadGuide database the first time with existing files
            self.database = PgRawDatabase(data_dir=self.settings.dataDir())
            self._is_ready.set()
            print('Finished initial PadGuide2 load with existing database')
        except Exception as ex:
            print(ex)
            print('Initial PadGuide2 database load failed, waiting for download')

        while self == self.bot.get_cog('PadGuide2'):
            short_wait = False
            try:
                await self.download_and_refresh_nicknames()
                print('Done refreshing PadGuide2, triggering ready')
                self._is_ready.set()
            except Exception as ex:
                short_wait = True
                print("padguide2 data download/refresh failed", ex)
                traceback.print_exc()

            try:
                await self.translate_names()
            except Exception as ex:
                print("translations failed", ex)
                traceback.print_exc()

            try:
                wait_time = 60 if short_wait else 60 * 60 * 4
                await asyncio.sleep(wait_time)
            except Exception as ex:
                print("padguide2 data wait loop failed", ex)
                traceback.print_exc()
                raise ex

    async def reload_config_files(self):
        os.remove(NICKNAME_FILE_PATTERN)
        os.remove(BASENAME_FILE_PATTERN)
        os.remove(PANTHNAME_FILE_PATTERN)
        await self.download_and_refresh_nicknames()

    async def translate_names(self):
        if os.path.exists(TRANSLATEDNAMES_EXPORT_PATH):
            with open(TRANSLATEDNAMES_EXPORT_PATH) as f:
                self.translated_names = json.load(f)

        for m in self.database.all_monsters():
            name_jp = m.name_jp
            if rpadutils.containsJp(name_jp) and name_jp not in self.translated_names:
                self.translated_names[name_jp] = await rpadutils.translate_jp_en(self.bot, name_jp)
            m.translated_jp_name = self.translated_names.get(name_jp, None)

        with open(TRANSLATEDNAMES_EXPORT_PATH, 'w', encoding='utf-8') as f:
            json.dump(self.translated_names, f, sort_keys=True, indent=4)

    async def download_and_refresh_nicknames(self):
        if not self.settings.dataDir():
            await self._download_files()
        await self._download_override_files()

        nickname_overrides = self._csv_to_tuples(NICKNAME_FILE_PATTERN)
        basename_overrides = self._csv_to_tuples(BASENAME_FILE_PATTERN)
        panthname_overrides = self._csv_to_tuples(PANTHNAME_FILE_PATTERN)

        self.nickname_overrides = {x[0].lower(): int(x[1])
                                   for x in nickname_overrides if x[1].isdigit()}

        self.basename_overrides = defaultdict(set)
        for x in basename_overrides:
            k, v = x
            if k.isdigit():
                self.basename_overrides[int(k)].add(v.lower())
        
        self.panthname_overrides = {x[0].lower(): x[1].lower() for x in panthname_overrides}
        self.panthname_overrides.update({v: v for _, v in self.panthname_overrides.items()})

        self.database = PgRawDatabase(data_dir=self.settings.dataDir())
        self.index = MonsterIndex(self.database, self.nickname_overrides, self.basename_overrides, self.panthname_overrides)

        self.write_monster_attr_data()
        self.write_monster_computed_names()

    def write_monster_computed_names(self):
        results = {}
        for name, nm in self.index.all_entries.items():
            results[name] = int(rpadutils.get_pdx_id(nm))

        with open(NAMES_EXPORT_PATH, 'w', encoding='utf-8') as f:
            json.dump(results, f, sort_keys=True)

        results = {}
        for nm in self.index.all_monsters:
            entry = {'bn': list(nm.group_basenames)}
            if nm.extra_nicknames:
                entry['nn'] = list(nm.extra_nicknames)
            results[int(rpadutils.get_pdx_id(nm))] = entry

        with open(BASENAMES_EXPORT_PATH, 'w', encoding='utf-8') as f:
            json.dump(results, f, sort_keys=True)

    def write_monster_attr_data(self):
        """Write id,server,attr1,attr2 to be used by the portrait generation process."""
        attr_short_prefix_map = {
            Attribute.Fire: 'r',
            Attribute.Water: 'b',
            Attribute.Wood: 'g',
            Attribute.Light: 'l',
            Attribute.Dark: 'd',
        }

        # Monsters who exist only in na have the same na/jp id but differing monster_no
        na_only = [x for x in self.database._monster_map.values() if x.monster_no !=
                   x.monster_no_na and x.monster_no_na == x.monster_no_jp]

        na_only_base_no = [x.monster_no for x in na_only]
        na_only_server_no = [x.monster_no_na for x in na_only]

        with open(ATTR_EXPORT_PATH, 'w') as csvfile:
            writer = csv.writer(csvfile, delimiter=',', lineterminator='\n')
            for m in self.database._monster_map.values():
                attr1 = attr_short_prefix_map[m.attr1]
                attr2 = attr_short_prefix_map[m.attr2] if m.attr2 else ''
                if m.monster_no in na_only_base_no:
                    # Writes stuff like voltron
                    writer.writerow([m.monster_no_na, 'na', attr1, attr2])
                elif m.monster_no_jp in na_only_server_no:
                    # Writes stuff like crows
                    writer.writerow([m.monster_no_jp, 'jp', attr1, attr2])
                else:
                    # writes everything else
                    writer.writerow([m.monster_no_na, 'na', attr1, attr2])
                    writer.writerow([m.monster_no_jp, 'jp', attr1, attr2])

    def _csv_to_tuples(self, file_path: str, cols: int=2):
        # Loads a two-column CSV into an array of tuples.
        results = []
        with open(file_path, encoding='utf-8') as f:
            file_reader = csv.reader(f, delimiter=',')
            for row in file_reader:
                if len(row) < 2:
                    continue

                data = [None] * cols
                for i in range(0, min(cols, len(row))):
                    data[i] = row[i].strip()

                if not len(data[0]):
                    continue

                results.append(data)
        return results

    async def _download_files(self):
        # twelve hours expiry
        standard_expiry_secs = 12 * 60 * 60
        # four hours expiry
        quick_expiry_secs = 4 * 60 * 60

        # Use a dummy file to proxy for the entire database being out of date
        general_dummy_file = DUMMY_FILE_PATTERN.format('general')
        download_all = rpadutils.checkPadguideCacheFile(general_dummy_file, quick_expiry_secs)

        async with aiohttp.ClientSession() as client_session:
            for type in self._standard_refresh:
                endpoint = type.file_name()
                result_file = JSON_FILE_PATTERN.format(endpoint)
                if download_all or rpadutils.should_download(result_file, quick_expiry_secs):
                    await rpadutils.async_cached_padguide_request(client_session, endpoint, result_file)
                    # Sleep to avoid overwhelming with requests
                    await asyncio.sleep(1)

            for type in self._quick_refresh:
                cur_time = int(round(time.time() * 1000))
                three_weeks_ago = cur_time - 3 * 7 * 24 * 60 * 60 * 1000
                endpoint = type.file_name()
                result_file = JSON_FILE_PATTERN.format(endpoint)
                if download_all or rpadutils.should_download(result_file, quick_expiry_secs):
                    await rpadutils.async_cached_padguide_request(client_session, endpoint, result_file, time_ms=three_weeks_ago)

    async def _download_override_files(self):
        overrides_expiry_secs = 1 * 60 * 60
        await rpadutils.makeAsyncCachedPlainRequest(
            NICKNAME_FILE_PATTERN, NICKNAME_OVERRIDES_SHEET, overrides_expiry_secs)
        await rpadutils.makeAsyncCachedPlainRequest(
            BASENAME_FILE_PATTERN, GROUP_BASENAMES_OVERRIDES_SHEET, overrides_expiry_secs)
        await rpadutils.makeAsyncCachedPlainRequest(
            PANTHNAME_FILE_PATTERN, PANTHNAME_OVERRIDES_SHEET, overrides_expiry_secs)

    @commands.group(pass_context=True)
    @checks.is_owner()
    async def padguide2(self, ctx):
        """PAD database management"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @padguide2.command(pass_context=True)
    @checks.is_owner()
    async def setdatadir(self, ctx, *, data_dir):
        """Set a local path to padguide data instead of downloading it."""
        self.settings.setDataDir(data_dir)
        await self.bot.say(inline('Done'))


class PadGuide2Settings(CogSettings):
    def make_default_settings(self):
        config = {
            'data_dir': '',
        }
        return config

    def dataDir(self):
        return self.bot_settings['data_dir']

    def setDataDir(self, data_dir):
        self.bot_settings['data_dir'] = data_dir
        self.save_settings()


def setup(bot):
    n = PadGuide2(bot)
    bot.add_cog(n)
    n.register_tasks()


class PgRawDatabase(object):
    def __init__(self, skip_load=False, data_dir=None):
        self._skip_load = skip_load
        self._data_dir = data_dir
        self._all_pg_items = []

        # Load raw data items into id->value maps
        self._attribute_map = self._load(PgAttribute)
        self._awakening_map = self._load(PgAwakening)
        self._dungeon_map = self._load(PgDungeon)
        # self._dungeon_damage_map = self._load(PgDungeonDamage)
        self._dungeon_monster_drop_map = self._load(PgDungeonMonsterDrop)
        self._dungeon_monster_map = self._load(PgDungeonMonster)
        # self._dungeon_skill_map = self._load(PgDungeonSkill)
        # self._dungeon_type_map = self._load(PgDungeonType)
        self._event_map = self._load(PgEvent)
        self._evolution_map = self._load(PgEvolution)
        self._evolution_material_map = self._load(PgEvolutionMaterial)
        self._monster_map = self._load(PgMonster)
        self._monster_add_info_map = self._load(PgMonsterAddInfo)
        self._monster_info_map = self._load(PgMonsterInfo)
        self._monster_price_map = self._load(PgMonsterPrice)
        self._series_map = self._load(PgSeries)
        self._scheduled_event_map = self._load(PgScheduledEvent)
        self._skill_leader_data_map = self._load(PgSkillLeaderData)
        self._skill_map = self._load(PgSkill)
        self._skill_rotation_map = self._load(PgSkillRotation)
        self._skill_rotation_dated_map = self._load(PgSkillRotationDated)
        # self._sub_dungeon_map = self._load(PgSubDungeon)
        self._type_map = self._load(PgType)

        self._egg_instance_map = self._load(PgEggInstance)
        self._egg_monster_map = self._load(PgEggMonster)
        self._egg_name_map = self._load(PgEggName)

        # Ensure that every item has loaded its dependencies
        for i in self._all_pg_items:
            self._ensure_loaded(i)

        # Finish loading now that all the dependencies are resolved
        for i in self._all_pg_items:
            i.finalize()

        # Stick the monsters into groups so that we can calculate info across
        # the entire group
        self.grouped_monsters = list()
        for m in self._monster_map.values():
            if m.cur_evo_type != EvoType.Base:
                continue
            self.grouped_monsters.append(MonsterGroup(m))

        # Used to normalize from monster NA values back to monster number
        self.monster_no_na_to_monster_no = {
            m.monster_no_na: m.monster_no for m in self._monster_map.values()}

        # Skill rotation map
        self._server_to_rotating_skillups = {
            'NA': [],
            'JP': [],
        }
        for m in self._monster_map.values():
            for server in m.server_actives:
                self._server_to_rotating_skillups[server].append(m)

    def _load(self, itemtype):
        if self._skip_load:
            return {}

        if self._data_dir:
            file_path = os.path.join(self._data_dir, '{}.json'.format(itemtype.file_name()))
        else:
            file_path = JSON_FILE_PATTERN.format(itemtype.file_name())
        item_list = []

        if dataIO.is_valid_json(file_path):
            json_data = dataIO.load_json(file_path)
            item_list = [itemtype(item) for item in json_data['items']]

        result_map = {item.key(): item for item in item_list if not item.deleted()}

        self._all_pg_items.extend(result_map.values())

        return result_map

    def _ensure_loaded(self, item: 'PgItem'):
        if item:
            item.ensure_loaded(self)
        return item

    def normalize_monster_no_na(self, monster_no_na: int):
        if monster_no_na > 10000:
            # Allows crows to be referenced
            return monster_no_na - 10000
        return self.monster_no_na_to_monster_no[monster_no_na]

    def all_monsters(self):
        """Exported for access to the full monster list."""
        return list(self._monster_map.values())

    def all_dungeons(self):
        """Exported for access to the full dungeon list."""
        return list(self._dungeon_map.values())

    def all_egg_instances(self):
        """Exported for access to the full egg machine list."""
        return list(self._egg_instance_map.values())

    def all_scheduled_events(self):
        """Exported for access to event list."""
        se = list(self._scheduled_event_map.values())
        return se

    def rotating_skillups(self, server: str):
        """Gets monsters used as rotating skillups for the specified server"""
        return list(self._server_to_rotating_skillups[server])

    def getAttributeEnum(self, ta_seq: int):
        attr = self._ensure_loaded(self._attribute_map.get(ta_seq))
        return attr.value if attr else None

    def getAwakening(self, tma_seq: int):
        return self._ensure_loaded(self._awakening_map.get(tma_seq))

    def getDungeon(self, dungeon_seq: int):
        return self._ensure_loaded(self._dungeon_map.get(dungeon_seq))

#    def getDungeonDamage(self, tds_seq: int):
#        return self._ensure_loaded(self._dungeon_damage_map.get(tds_seq))

    def getDungeonMonsterDrop(self, tdmd_seq: int):
        return self._ensure_loaded(self._dungeon_monster_drop_map.get(tdmd_seq))

    def getDungeonMonster(self, tdm_seq: int):
        return self._ensure_loaded(self._dungeon_monster_map.get(tdm_seq))

#    def getDungeonType(self, tdt_seq: int):
#        return self._ensure_loaded(self._dungeon_type_map.get(tdt_seq))

    def getEvent(self, event_seq: int):
        return self._ensure_loaded(self._event_map.get(event_seq))

    def getEvolution(self, tv_seq: int):
        return self._ensure_loaded(self._evolution_map.get(tv_seq))

    def getEvolutionMaterial(self, tem_seq: int):
        return self._ensure_loaded(self._evolution_material_map.get(tem_seq))

    def getMonster(self, monster_no: int):
        return self._ensure_loaded(self._monster_map.get(monster_no))

    def getMonsterAddInfo(self, monster_no: int):
        return self._ensure_loaded(self._monster_add_info_map.get(monster_no))

    def getMonsterInfo(self, monster_no: int):
        return self._ensure_loaded(self._monster_info_map.get(monster_no))

    def getMonsterPrice(self, monster_no: int):
        return self._ensure_loaded(self._monster_price_map.get(monster_no))

    def getSeries(self, tsr_seq: int):
        return self._ensure_loaded(self._series_map.get(tsr_seq))

    def getScheduledEvent(self, schedule_seq: int):
        return self._ensure_loaded(self._scheduled_event_map.get(schedule_seq))

    def getSkill(self, ts_seq: int):
        return self._ensure_loaded(self._skill_map.get(ts_seq))

    def getSkillLeaderData(self, ts_seq: int):
        skill_leader = self._skill_leader_data_map.get(ts_seq)
        if skill_leader:
            return self._ensure_loaded(skill_leader)
        else:
            return PgSkillLeaderData.empty()

    def getSkillRotation(self, tsr_seq: int):
        return self._ensure_loaded(self._skill_rotation_map.get(tsr_seq))

    def getSkillRotationDated(self, tsrl_seq: int):
        return self._ensure_loaded(self._skill_rotation_dated_map.get(tsrl_seq))

#    def getSubDungeon(self, tsd_seq: int):
#        return self._ensure_loaded(self._sub_dungeon_map.get(tsd_seq))

    def getTypeName(self, tt_seq: int):
        type = self._ensure_loaded(self._type_map.get(tt_seq))
        return type.name if type else None

    def getEggInstance(self, tet_seq: int):
        return self._ensure_loaded(self._egg_instance_map.get(tet_seq))

    def getEggMonster(self, tem_seq: int):
        return self._ensure_loaded(self._egg_monster_map.get(tem_seq))

    def getEggName(self, tetn_seq: int):
        return self._ensure_loaded(self._egg_name_map.get(tetn_seq))


class PgItem(object):
    """Base class for all items loaded from PadGuide.

    You must call super().__init__() in your constructor.
    You must override key() and load().
    """

    def __init__(self):
        self._loaded = False

    def key(self):
        """Used to look up an item by id."""
        raise NotImplementedError()

    def deleted(self):
        """Is this item marked for deletion. Discard if true. Not all items can be deleted."""
        return False

    def ensure_loaded(self, database: PgRawDatabase):
        """Ensures that the dependencies have been loaded, or loads them."""
        if not self._loaded:
            self._loaded = True
            self._loading_error = False
            try:
                self.load(database)
            except Exception as ex:
                self._loading_error = False
                print('Error occurred while loading item')
                print(type(self), 'key=', self.key())
                traceback.print_exc()

        return self

    def load(self, database: PgRawDatabase):
        """Override to inject dependencies."""
        raise NotImplementedError()

    def finalize(self):
        """Finish filling in anything that requires completion but no dependencies."""
        pass


class Attribute(Enum):
    """Standard 5 PAD colors in enum form. Values correspond to PadGuide values."""
    Fire = 1
    Water = 2
    Wood = 3
    Light = 4
    Dark = 5


# attributeList
# {
#     "ORDER_IDX": "2",
#     "TA_NAME_JP": "\u6c34",
#     "TA_NAME_KR": "\ubb3c",
#     "TA_NAME_US": "Water",
#     "TA_SEQ": "2",
#     "TSTAMP": "1372947975226"
# },
class PgAttribute(PgItem):
    @staticmethod
    def file_name():
        return 'attributeList'

    def __init__(self, item):
        super().__init__()
        self.ta_seq = int(item['TA_SEQ'])  # unique id
        self.name = item['TA_NAME_US']

        self.value = Attribute(self.ta_seq)

    def key(self):
        return self.ta_seq

    def load(self, database: PgRawDatabase):
        pass


# awokenSkillList
# {
#     "DEL_YN": "N",
#     "IS_SUPER": "1",
#     "MONSTER_NO": "661",
#     "ORDER_IDX": "1",
#     "TMA_SEQ": "1",
#     "TSTAMP": "1380587210665",
#     "TS_SEQ": "2769"
# },
class PgAwakening(PgItem):
    @staticmethod
    def file_name():
        return 'awokenSkillList'

    def __init__(self, item):
        super().__init__()
        self.tma_seq = int(item['TMA_SEQ'])  # unique id
        self.ts_seq = int(item['TS_SEQ'])  # PgSkill id - awakening info
        self.deleted_yn = item['DEL_YN']  # Either Y(discard) or N.
        self.monster_no = int(item['MONSTER_NO'])  # PgMonster id - monster this belongs to
        self.order = int(item['ORDER_IDX'])  # display order
        self.is_super = item.get('IS_SUPER', '0') == '1'

        self.skill = None  # type: PgSkill  # The awakening skill
        self.monster = None  # type: PgMonster # The monster the awakening belongs to

    def key(self):
        return self.tma_seq

    def deleted(self):
        return self.deleted_yn == 'Y'

    def load(self, database: PgRawDatabase):
        self.skill = database.getSkill(self.ts_seq)
        self.monster = database.getMonster(self.monster_no)

        self.monster.awakenings.append(self)
        self.skill.monsters_with_awakening.append(self.monster)

    def get_name(self):
        return self.skill.name


# dungeonList
# {
#     "APP_VERSION": "",
#     "COMMENT_JP": "",
#     "COMMENT_KR": "",
#     "COMMENT_US": "",
#     "DUNGEON_SEQ": "102",
#     "DUNGEON_TYPE": "1",
#     "ICON_SEQ": "666",
#     "NAME_JP": "ECO\u30b3\u30e9\u30dc",
#     "NAME_KR": "ECO \ucf5c\ub77c\ubcf4",
#     "NAME_US": "ECO Collab",
#     "ORDER_IDX": "3",
#     "SHOW_YN": "1",
#     "TDT_SEQ": "10",
#     "TSTAMP": "1373289123410"
# },
class PgDungeon(PgItem):
    @staticmethod
    def file_name():
        return 'dungeonList'

    def __init__(self, item):
        super().__init__()
        self.dungeon_seq = int(item['DUNGEON_SEQ'])
        self.dungeon_type = int(item['DUNGEON_TYPE'])
        # TODO: merge these two, delete DungeonType from padevents
        self.dungeon_type_value = DungeonType(self.dungeon_type)
        self.name = item['NAME_US']
        self.name_jp = item['NAME_JP']
        # TODO: load tdt type
        self.tdt_seq = int_or_none(item['TDT_SEQ'])
        self.show = item['SHOW_YN'] == 1
        self.icon = int(item['ICON_SEQ'])

        self.tdungeon_type = None
        self.tdungeon_type_name = 'no_type'

        self.monsters = []
        self.subdungeons = []

    def key(self):
        return self.dungeon_seq

    def deleted(self):
        return False
#         return not self.show

    def load(self, database: PgRawDatabase):
        pass
#        if self.tdt_seq:
#            self.tdungeon_type = database.getDungeonType(self.tdt_seq)
#            # Somehow this can still fail
#            if self.tdungeon_type:
#                self.tdungeon_type_name = self.tdungeon_type.name


class DungeonType(Enum):
    Unknown = -1
    Normal = 0
    CoinDailyOther = 1
    Technical = 2
    Etc = 3


# {
#     "COIN_MAX": "2496",
#     "COIN_MIN": "2496",
#     "DUNGEON_SEQ": "81",
#     "EXP_MAX": "2420",
#     "EXP_MIN": "2420",
#     "ORDER_IDX": "96",
#     "STAGE": "5",
#     "STAMINA": "15",
#     "TSD_NAME_JP": "\u65ad\u7f6a\u306e\u7114 \u4e2d\u7d1a",
#     "TSD_NAME_KR": "\ub2e8\uc8c4\uc758 \ubd88\uaf43 \uc911\uae09",
#     "TSD_NAME_US": "Flame of Conviction - Int",
#     "TSD_SEQ": "1365",
#     "TSTAMP": "1373446281337"
# },
class PgSubDungeon(PgItem):
    @staticmethod
    def file_name():
        return 'subDungeonList'

    def __init__(self, item):
        super().__init__()
        self.dungeon_seq = int(item['DUNGEON_SEQ'])
        self.exp_max = int(item['EXP_MAX'])
        self.exp_min = int(item['EXP_MIN'])
        self.order = int(item['ORDER_IDX'])
        self.stage = int(item['STAGE'])
        self.stamina = int(item['STAMINA'])
        self.name = item['TSD_NAME_US']
        self.tsd_seq = int(item['TSD_SEQ'])

        self.monsters = []
        self.floor_to_monsters = defaultdict(list)

    def key(self):
        return self.tsd_seq

    def load(self, database: PgRawDatabase):
        self.dungeon = database.getDungeon(self.dungeon_seq)
        self.dungeon.subdungeons.append(self)


# dungeonMonsterDropList.jsp
# {
#     "MONSTER_NO": "3427",
#     "ORDER_IDX": "20",
#     "STATUS": "0",
#     "TDMD_SEQ": "967",
#     "TDM_SEQ": "17816",
#     "TSTAMP": "1489371218890"
# },
# Seems to be dedicated skillups only, like collab drops
class PgDungeonMonsterDrop(PgItem):
    @staticmethod
    def file_name():
        return 'dungeonMonsterDropList'

    def __init__(self, item):
        super().__init__()
        self.tdmd_seq = int(item['TDMD_SEQ'])  # unique id
        self.monster_no = int(item['MONSTER_NO'])
        self.status = item['STATUS']  # if 1, good, if 0, bad
        self.tdm_seq = int(item['TDM_SEQ'])  # PgDungeonMonster id

        self.monster = None  # type: PgMonster
        self.dungeon_monster = None  # type: PgDungeonMonster

    def key(self):
        return self.tdmd_seq

    def deleted(self):
        # TODO: Should we be checking status == 1?
        return False

    def load(self, database: PgRawDatabase):
        self.monster = database.getMonster(self.monster_no)
        self.dungeon_monster = database.getDungeonMonster(self.tdm_seq)


# dungeonMonsterList
# {
#     "AMOUNT": "1",
#     "ATK": "9810",
#     "COMMENT_JP": "",
#     "COMMENT_KR": "",
#     "COMMENT_US": "",
#     "DEF": "340",
#     "DROP_NO": "2789",
#     "DUNGEON_SEQ": "150",
#     "FLOOR": "5",
#     "HP": "3011250",
#     "MONSTER_NO": "2789",
#     "ORDER_IDX": "50",
#     "TDM_SEQ": "53122",
#     "TSD_SEQ": "4564",
#     "TSTAMP": "1480298353178",
#     "TURN": "1"
# },
class PgDungeonMonster(PgItem):
    @staticmethod
    def file_name():
        return 'dungeonMonsterList'

    def __init__(self, item):
        super().__init__()
        self.tdm_seq = int(item['TDM_SEQ'])  # unique id
        self.amount = int(item['AMOUNT'])
        self.atk = int(item['ATK'])
        self.defence = int(item['DEF'])
        self.drop_monster_no = int(item['DROP_NO'])  # PgMonster unique id
        self.dungeon_seq = int(item['DUNGEON_SEQ'])  # PgDungeon uniqueId
        self.floor = int(item['FLOOR'])
        self.hp = int(item['HP'])
        self.monster_no = int(item['MONSTER_NO'])  # PgMonster unique id
        self.order = int(item['ORDER_IDX'])
        self.tsd_seq = int(item['TSD_SEQ'])  # Sub Dungeon ID
        self.turn = int(item['TURN'])

        self.skills = []

    def key(self):
        return self.tdm_seq

    def load(self, database: PgRawDatabase):
        self.monster = database.getMonster(self.monster_no)

        self.dungeon = database.getDungeon(self.dungeon_seq)
        if self.dungeon:
            self.dungeon.monsters.append(self)

#         self.sub_dungeon = database.getSubDungeon(self.tsd_seq)
#         self.sub_dungeon.monsters.append(self)
#         self.sub_dungeon.floor_to_monsters[self.floor].append(self)

        self.drop_monster = database.getMonster(self.drop_monster_no)
        if self.drop_monster and self.dungeon:
            self.drop_monster.drop_dungeons.append(self.dungeon)


# {
#     "TDM_SEQ": "15044", # dungeon monster
#     "TDS_SEQ": "8934", # damage
#     "TSTAMP": "100",
#     "TS_SEQ": "2190" # skill
# },
class PgDungeonSkill(PgItem):
    @staticmethod
    def file_name():
        return 'dungeonSkillList'

    def __init__(self, item):
        super().__init__()
        self.tdm_seq = int(item['TDM_SEQ'])
        self.tds_seq = int(item['TDS_SEQ'])
        self.ts_seq = int(item['TS_SEQ'])

    def key(self):
        return '{},{},{}'.format(self.tdm_seq, self.tds_seq, self.ts_seq)

    def load(self, database: PgRawDatabase):
        self.dungeon_monster = database.getDungeonMonster(self.tdm_seq)
        if self.dungeon_monster:
            self.dungeon_monster.skills.append(self)
        self.damage = database.getDungeonDamage(self.tds_seq)
        self.skill = database.getSkill(self.ts_seq)


# {
#     "DAMAGE": "16538.0",
#     "TDS_SEQ": "14631",
#     "TSTAMP": "1401764306350"
# },
class PgDungeonDamage(PgItem):
    @staticmethod
    def file_name():
        return 'dungeonSkillDamageList'

    def __init__(self, item):
        super().__init__()
        self.tds_seq = int(item['TDS_SEQ'])
        self.amount = float(item['DAMAGE'])

        self.monsters = []
        self.floor_to_monsters = defaultdict(list)

    def key(self):
        return self.tds_seq

    def load(self, database: PgRawDatabase):
        pass


# {
#     "ORDER_IDX": "120",
#     "TDT_NAME_JP": "\u30a2\u30f3\u30b1\u30fc\u30c8",
#     "TDT_NAME_KR": "\uc559\ucf00\uc774\ud2b8",
#     "TDT_NAME_US": "Survey",
#     "TDT_SEQ": "9",
#     "TSTAMP": "1388128221704"
# },
class PgDungeonType(PgItem):
    @staticmethod
    def file_name():
        return 'dungeonTypeList'

    def __init__(self, item):
        super().__init__()
        self.name = item['TDT_NAME_US']
        self.tdt_seq = int(item['TDT_SEQ'])

    def key(self):
        return self.tdt_seq

    def load(self, database: PgRawDatabase):
        pass


class EvoType(Enum):
    """Evo types supported by PadGuide. Numbers correspond to their id values."""
    Base = -1  # Represents monsters who didn't require evo
    Evo = 0
    UvoAwoken = 1
    UuvoReincarnated = 2


# evolutionList
# {
#     "APP_VERSION": "",
#     "COMMENT_JP": "",
#     "COMMENT_KR": "",
#     "COMMENT_US": "",
#     "MONSTER_NO": "1",
#     "TO_NO": "2",
#     "TSTAMP": "1371788673999",
#     "TV_SEQ": "331",
#     "TV_TYPE": "0"
# },
class PgEvolution(PgItem):
    @staticmethod
    def file_name():
        return 'evolutionList'

    def __init__(self, item):
        super().__init__()
        self.tv_seq = int(item['TV_SEQ'])  # unique id
        self.from_monster_no = int(item['MONSTER_NO'])  # PgMonster id - base monster
        self.to_monster_no = int(item['TO_NO'])  # PgMonster id - target monster
        self.tv_type = int(item['TV_TYPE'])
        self.evo_type = EvoType(self.tv_type)

    def key(self):
        return self.tv_seq

    def deleted(self):
        # Really rare and unusual bug
        return self.from_monster_no == 0 or self.to_monster_no == 0

    def load(self, database: PgRawDatabase):
        self.from_monster = database.getMonster(self.from_monster_no)
        self.to_monster = database.getMonster(self.to_monster_no)

        if self.to_monster:
            self.to_monster.cur_evo_type = self.evo_type
            if self.from_monster:
                self.to_monster.evo_from = self.from_monster
                self.from_monster.evo_to.append(self.to_monster)


# evoMaterialList
# {
#     "MONSTER_NO": "153",
#     "ORDER_IDX": "1",
#     "TEM_SEQ": "1429",
#     "TSTAMP": "1371788674011",
#     "TV_SEQ": "332"
# },
class PgEvolutionMaterial(PgItem):
    @staticmethod
    def file_name():
        return 'evoMaterialList'

    def __init__(self, item):
        super().__init__()
        self.tem_seq = int(item['TEM_SEQ'])  # unique id
        self.tv_seq = int(item['TV_SEQ'])  # evo id
        self.fodder_monster_no = int(item['MONSTER_NO'])  # material monster
        self.order = int(item['ORDER_IDX'])  # display order

        self.evolution = None  # type: PgEvolution
        self.fodder_monster = None  # type: PgMonster

    def key(self):
        return self.tem_seq

    def load(self, database: PgRawDatabase):
        self.evolution = database.getEvolution(self.tv_seq)
        self.fodder_monster = database.getMonster(self.fodder_monster_no)

        if self.evolution is None or self.evolution.to_monster is None:
            # Really rare and unusual bug
            return

        target_monster = self.evolution.to_monster
        # TODO: this is unsorted
        target_monster.mats_for_evo.append(self.fodder_monster)

        # Prevent issues if a monster is a mat for the same monster repeatedly (gunma, stones)
        if target_monster not in self.fodder_monster.material_of:
            self.fodder_monster.material_of.append(target_monster)


# monsterAddInfoList
# {
#     "EXTRA_VAL1": "1",
#     "EXTRA_VAL2": "",
#     "EXTRA_VAL3": "",
#     "EXTRA_VAL4": "",
#     "EXTRA_VAL5": "",
#     "MONSTER_NO": "3329",
#     "SUB_TYPE": "0",
#     "TSTAMP": "1480435906788"
# },
class PgMonsterAddInfo(PgItem):
    """Optional extra information for a Monster.

    Data is copied into PgMonster and this is discarded."""

    @staticmethod
    def file_name():
        return 'monsterAddInfoList'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.sub_type = int(item['SUB_TYPE'])
        self.extra_val_1 = int_or_none(item['EXTRA_VAL1'])

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        pass


# monsterInfoList
# {
#     "FODDER_EXP": "675.0",
#     "HISTORY_JP": "[2016-12-16] \u65b0\u898f\u8ffd\u52a0",
#     "HISTORY_KR": "[2016-12-16] \uc2e0\uaddc\ucd94\uac00",
#     "HISTORY_US": "[2016-12-16] New Added",
#     "MONSTER_NO": "3382",
#     "ON_KR": "1",
#     "ON_US": "1",
#     "PAL_EGG": "0",
#     "RARE_EGG": "0",
#     "SELL_PRICE": "300.0",
#     "TSR_SEQ": "86",
#     "TSTAMP": "1481846935838"
# },
class PgMonsterInfo(PgItem):
    """Extra information for a Monster.

    Data is copied into PgMonster and this is discarded."""

    @staticmethod
    def file_name():
        return 'monsterInfoList'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.on_na = item['ON_US'] == '1'
        self.tsr_seq = int_or_none(item['TSR_SEQ'])  # PgSeries id
        self.in_pem = item['PAL_EGG'] == '1'
        self.in_rem = item['RARE_EGG'] == '1'
        self.history_us = item['HISTORY_US']

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        self.series = database.getSeries(self.tsr_seq)


# monsterList
# {
#     "APP_VERSION": "0.0",
#     "ATK_MAX": "1985",
#     "ATK_MIN": "695",
#     "COMMENT_JP": "",
#     "COMMENT_KR": "\uc77c\ubcf8",
#     "COMMENT_US": "Japan",
#     "COST": "60",
#     "EXP": "10000000",
#     "HP_MAX": "6258",
#     "HP_MIN": "3528",
#     "LEVEL": "99",
#     "MONSTER_NO": "3646",
#     "MONSTER_NO_JP": "3646",
#     "MONSTER_NO_KR": "3646",
#     "MONSTER_NO_US": "3646",
#     "PRONUNCIATION_JP": "\u304b\u306a\u305f\u306a\u308b\u3082\u306e\u30fb\u3088\u3050\u305d\u3068\u30fc\u3059",
#     "RARITY": "7",
#     "RATIO_ATK": "1.5",
#     "RATIO_HP": "1.5",
#     "RATIO_RCV": "1.5",
#     "RCV_MAX": "233",
#     "RCV_MIN": "926",
#     "REG_DATE": "2017-04-27 17:29:48.0",
#     "TA_SEQ": "4",
#     "TA_SEQ_SUB": "0",
#     "TE_SEQ": "14",
#     "TM_NAME_JP": "\u5f7c\u65b9\u306a\u308b\u3082\u306e\u30fb\u30e8\u30b0\uff1d\u30bd\u30c8\u30fc\u30b9",
#     "TM_NAME_KR": "\u5f7c\u65b9\u306a\u308b\u3082\u306e\u30fb\u30e8\u30b0\uff1d\u30bd\u30c8\u30fc\u30b9",
#     "TM_NAME_US": "\u5f7c\u65b9\u306a\u308b\u3082\u306e\u30fb\u30e8\u30b0\uff1d\u30bd\u30c8\u30fc\u30b9",
#     "TSTAMP": "1494033700775",
#     "TS_SEQ_LEADER": "12448",
#     "TS_SEQ_SKILL": "12447",
#     "TT_SEQ": "10",
#     "TT_SEQ_SUB": "1"
# }
class PgMonster(PgItem):
    @staticmethod
    def file_name():
        return 'monsterList'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.monster_no_na = int(item['MONSTER_NO_US'])
        self.monster_no_jp = int(item['MONSTER_NO_JP'])
        self.min_hp = int(item['HP_MIN'])
        self.min_atk = int(item['ATK_MIN'])
        self.min_rcv = int(item['RCV_MIN'])
        self.hp = int(item['HP_MAX'])
        self.atk = int(item['ATK_MAX'])
        self.rcv = int(item['RCV_MAX'])
        self.ts_seq_active = int_or_none(item['TS_SEQ_SKILL'])
        self.ts_seq_leader = int_or_none(item['TS_SEQ_LEADER'])
        self.rarity = int(item['RARITY'])
        self.cost = int(item['COST'])
        self.exp = int(item['EXP'])
        self.max_level = int(item['LEVEL'])
        self.name_na = item['TM_NAME_US']
        self.name_jp = item['TM_NAME_JP']
        self.ta_seq_1 = int(item['TA_SEQ'])  # PgAttribute id
        self.ta_seq_2 = int(item['TA_SEQ_SUB'])  # PgAttribute id
        self.te_seq = int(item['TE_SEQ'])
        self.tt_seq_1 = int(item['TT_SEQ'])  # PgType id
        self.tt_seq_2 = int(item['TT_SEQ_SUB'])  # PgType id

        self.debug_info = ''
        self.weighted_stats = int(self.hp / 10 + self.atk / 5 + self.rcv / 3)

        self.roma_subname = None
        if self.name_na == self.name_jp:
            self.roma_subname = make_roma_subname(self.name_jp)
        else:
            # Remove annoying stuff from NA names, like Jörmungandr
            self.name_na = rpadutils.rmdiacritics(self.name_na)

        self.active_skill = None  # type: PgSkill
        self.leader_skill = None  # type: PgSkill

        # ???
        self.cur_evo_type = EvoType.Base
        self.evo_to = []
        self.evo_from = None

        self.mats_for_evo = []
        self.material_of = []

        self.awakenings = []  # PgAwakening
        self.drop_dungeons = []

        self.alt_evos = []  # PgMonster

        # List of PgSkillRotationDated
        self.rotating_skillups = []
        self.server_actives = {}  # str(NA, JP) -> PgSkill
        self.future_skillup_rotation = {}

        self.is_equip = False

        # Monsters start off pointing to themselves as the base, this will
        # change once the MonsterGroups are computed.
        self.base_monster = self

        # Data populated via override
        self.limitbreak_stats = 1 + float(item['LIMIT_MULT']) / 100 if item['LIMIT_MULT'] else None
        self.superawakening_count = 0

        # Data filled in post-load
        self.translated_jp_name = None

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        self.active_skill = database.getSkill(self.ts_seq_active)
        if self.active_skill:
            self.active_skill.monsters_with_active.append(self)

        self.leader_skill = database.getSkill(self.ts_seq_leader)
        self.leader_skill_data = database.getSkillLeaderData(self.ts_seq_leader)
        if self.leader_skill:
            self.leader_skill.monsters_with_leader.append(self)

        self.attr1 = database.getAttributeEnum(self.ta_seq_1)
        self.attr2 = database.getAttributeEnum(self.ta_seq_2)

        self.type1 = database.getTypeName(self.tt_seq_1)
        self.type2 = database.getTypeName(self.tt_seq_2)
        self.type3 = None

        self.assist_setting = None
        monster_add_info = database.getMonsterAddInfo(self.monster_no)
        if monster_add_info:
            self.type3 = database.getTypeName(monster_add_info.sub_type)
            self.assist_setting = monster_add_info.extra_val_1

        monster_info = database.getMonsterInfo(self.monster_no)
        self.on_na = monster_info.on_na
        self.series = database.getSeries(monster_info.tsr_seq)  # PgSeries
        self.series.monsters.append(self)
        self.is_gfe = self.series.tsr_seq == 34  # godfest
        self.in_pem = monster_info.in_pem
        self.in_rem = monster_info.in_rem
        self.pem_evo = self.in_pem
        self.rem_evo = self.in_rem
        self.history_us = monster_info.history_us

        monster_price = database.getMonsterPrice(self.monster_no)
        self.sell_mp = monster_price.sell_mp if monster_price else 0
        self.buy_mp = monster_price.buy_mp if monster_price else 0
        self.in_mpshop = self.buy_mp > 0
        self.mp_evo = self.in_mpshop

    def finalize(self):
        self.farmable = len(self.drop_dungeons) > 0
        self.farmable_evo = self.farmable

        self.awakenings.sort(key=lambda x: x.order)
        self.superawakening_count = sum(int(a.is_super) for a in self.awakenings)

        if self.assist_setting == 1:
            self.is_inheritable = True
        elif self.assist_setting == 2:
            self.is_inheritable = False
        else:
            has_awakenings = len(self.awakenings) > 0
            self.is_inheritable = has_awakenings and self.rarity >= 5 and self.sell_mp >= 3000

        self.is_equip = 'Awoken Assist' in [a.get_name() for a in self.awakenings]

        self.types = [t.lower() for t in [self.type1, self.type2, self.type3] if t]

        if self.evo_from is None:
            def link(m: PgMonster, alt_evos: list):
                alt_evos.append(m)
                m.alt_evos = alt_evos
                for em in m.evo_to:
                    link(em, alt_evos)
            link(self, [])

        self.search = MonsterSearchHelper(self)

        # Compute server skill rotations
        for server, server_tz in {'JP': rpadutils.JP_TZ_OBJ, 'NA': rpadutils.NA_TZ_OBJ}.items():
            server_now = datetime.now().replace(tzinfo=server_tz).date()
            server_skillups = list(filter(lambda s: s.skill_rotation.server == server,
                                          self.rotating_skillups))
            future_skillup = list(filter(lambda s: server_now < s.rotation_date, server_skillups))
            if future_skillup:
                self.future_skillup_rotation[server] = future_skillup[0]

            past_skillups = list(filter(lambda s: server_now >= s.rotation_date, server_skillups))
            if past_skillups:
                active_skillup = max(past_skillups, key=lambda s: s.rotation_date)
                self.server_actives[server] = active_skillup.skill
                active_skillup.skill.server_skillups[server] = active_skillup.skill_rotation.monster


class MonsterSearchHelper(object):
    def __init__(self, m: PgMonster):

        self.name = '{} {}'.format(m.name_na, m.name_jp).lower()
        self.leader = m.leader_skill.desc.lower() if m.leader_skill else ''
        self.active_name = m.active_skill.name.lower() if m.active_skill else ''
        self.active_desc = m.active_skill.desc.lower() if m.active_skill else ''
        self.active = '{} {}'.format(self.active_name, self.active_desc)
        self.active_min = m.active_skill.turn_min if m.active_skill else None
        self.active_max = m.active_skill.turn_max if m.active_skill else None

        self.color = [m.attr1.name.lower()]
        self.hascolor = [c.name.lower() for c in [m.attr1, m.attr2] if c]

        self.limitbreak_stats = m.limitbreak_stats or 1

        self.hp = m.hp * self.limitbreak_stats
        self.atk = m.atk * self.limitbreak_stats
        self.rcv = m.rcv * self.limitbreak_stats
        self.weighted_stats = m.weighted_stats * self.limitbreak_stats

        self.types = m.types

        def replace_colors(text: str):
            return text.replace('red', 'fire').replace('blue', 'water').replace('green', 'wood')
        self.leader = replace_colors(self.leader)
        self.active = replace_colors(self.active)
        self.active_name = replace_colors(self.active_name)
        self.active_desc = replace_colors(self.active_desc)

        self.board_change = []
        self.orb_convert = defaultdict(list)
        self.row_convert = []
        self.column_convert = []

        def color_txt_to_list(txt):
            txt = txt.replace('and', ' ')
            txt = txt.replace(',', ' ')
            txt = txt.replace('orbs', ' ')
            txt = txt.replace('orb', ' ')
            txt = txt.replace('mortal poison', 'mortalpoison')
            txt = txt.replace('jammers', 'jammer')
            txt = txt.strip()
            return txt.split()

        def strip_prev_clause(txt: str, sep: str):
            prev_clause_start_idx = txt.find(sep)
            if prev_clause_start_idx >= 0:
                prev_clause_start_idx += len(sep)
                txt = txt[prev_clause_start_idx:]
            return txt

        def strip_next_clause(txt: str, sep: str):
            next_clause_start_idx = txt.find(sep)
            if next_clause_start_idx >= 0:
                txt = txt[:next_clause_start_idx]
            return txt

        active_desc = self.active_desc
        active_desc = active_desc.replace(' rows ', ' row ')
        active_desc = active_desc.replace(' columns ', ' column ')
        active_desc = active_desc.replace(' into ', ' to ')
        active_desc = active_desc.replace('changes orbs to', 'all orbs to')

        board_change_txt = 'all orbs to'
        if board_change_txt in active_desc:
            txt = strip_prev_clause(active_desc, board_change_txt)
            txt = strip_next_clause(txt, 'orbs')
            txt = strip_next_clause(txt, ';')
            self.board_change = color_txt_to_list(txt)

        txt = active_desc
        if 'row' in txt:
            parts = re.split('\Wand\W|;\W', txt)
            for i in range(0, len(parts)):
                if 'row' in parts[i]:
                    self.row_convert.append(strip_next_clause(
                        strip_prev_clause(parts[i], 'to '), ' orbs'))

        txt = active_desc
        if 'column' in txt:
            parts = re.split('\Wand\W|;\W', txt)
            for i in range(0, len(parts)):
                if 'column' in parts[i]:
                    self.column_convert.append(strip_next_clause(
                        strip_prev_clause(parts[i], 'to '), ' orbs'))

        convert_done = self.board_change or self.row_convert or self.column_convert

        change_txt = 'change '
        if not convert_done and change_txt in active_desc and 'orb' in active_desc:
            txt = active_desc
            parts = re.split('\Wand\W|;\W', txt)
            for i in range(0, len(parts)):
                parts[i] = strip_prev_clause(parts[i], change_txt) if change_txt in parts[i] else ''

            for part in parts:
                sub_parts = part.split(' to ')
                if len(sub_parts) > 1:
                    source_orbs = color_txt_to_list(sub_parts[0])
                    dest_orbs = color_txt_to_list(sub_parts[1])
                    for so in source_orbs:
                        for do in dest_orbs:
                            self.orb_convert[so].append(do)


class MonsterGroup(object):
    """Computes shared values across a tree of monsters and injects them."""

    def __init__(self, base_monster: PgMonster):
        self.base_monster = base_monster
        self.members = list()
        self._recursive_add(base_monster)
        self._initialize_members()

    def _recursive_add(self, m: PgMonster):
        m.base_monster = self.base_monster
        self.members.append(m)
        for em in m.evo_to:
            self._recursive_add(em)

    def _initialize_members(self):
        # Compute tree acquisition status
        farmable_evo, pem_evo, rem_evo, mp_evo = False, False, False, False
        for m in self.members:
            farmable_evo = farmable_evo or m.farmable
            pem_evo = pem_evo or m.in_pem
            rem_evo = rem_evo or m.in_rem
            mp_evo = mp_evo or m.in_mpshop

        # Override tree acquisition status
        for m in self.members:
            m.farmable_evo = farmable_evo
            m.pem_evo = pem_evo
            m.rem_evo = rem_evo
            m.mp_evo = mp_evo


# monsterPriceList
# {
#     "BUY_PRICE": "0",
#     "MONSTER_NO": "3577",
#     "SELL_PRICE": "99",
#     "TSTAMP": "1492101772974"
# }


class PgMonsterPrice(PgItem):
    @staticmethod
    def file_name():
        return 'monsterPriceList'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.buy_mp = int(item['BUY_PRICE'])
        self.sell_mp = int(item['SELL_PRICE'])

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        pass


# seriesList
# {
#     "DEL_YN": "N",
#     "NAME_JP": "\u308a\u3093",
#     "NAME_KR": "\uc2ac\ub77c\uc784",
#     "NAME_US": "Slime",
#     "SEARCH_DATA": "\u308a\u3093 Slime \uc2ac\ub77c\uc784",
#     "TSR_SEQ": "3",
#     "TSTAMP": "1380587210667"
# },
class PgSeries(PgItem):
    @staticmethod
    def file_name():
        return 'seriesList'

    def __init__(self, item):
        super().__init__()
        self.tsr_seq = int(item['TSR_SEQ'])
        self.name = item['NAME_US']
        self.deleted_yn = item['DEL_YN']  # Either Y(discard) or N.

        self.monsters = []

    def key(self):
        return self.tsr_seq

    def deleted(self):
        return False
        # Temporary
#         return self.deleted_yn == 'Y'

    def load(self, database: PgRawDatabase):
        pass


# skillList
# {
#     "MAG_ATK": "0.0",
#     "MAG_HP": "0.0",
#     "MAG_RCV": "0.0",
#     "ORDER_IDX": "3",
#     "REDUCE_DMG": "0.0",
#     "RTA_SEQ_1": "0",
#     "RTA_SEQ_2": "0",
#     "SEARCH_DATA": "\u6e9c\u3081\u65ac\u308a \u6e9c\u3081\u65ac\u308a \u6e9c\u3081\u65ac\u308a 2\u30bf\u30fc\u30f3\u306e\u9593\u3001\u30c1\u30fc\u30e0\u5185\u306e\u30c9\u30e9\u30b4\u30f3\u30ad\u30e9\u30fc\u306e\u899a\u9192\u6570\u306b\u5fdc\u3058\u3066\u653b\u6483\u529b\u304c\u4e0a\u6607\u3002(1\u500b\u306b\u3064\u304d50%) Increase ATK depending on number of Dragon Killer Awakening Skills on team for 2 turns (50% per each) 2\ud134\uac04 \ud300\ub0b4\uc758 \ub4dc\ub798\uace4 \ud0ac\ub7ec \uac01\uc131 \uac2f\uc218\uc5d0 \ub530\ub77c \uacf5\uaca9\ub825\uc774 \uc0c1\uc2b9 (\uac1c\ub2f9 50%)",
#     "TA_SEQ_1": "0",
#     "TA_SEQ_2": "0",
#     "TSTAMP": "1493861895693",
#     "TS_DESC_JP": "2\u30bf\u30fc\u30f3\u306e\u9593\u3001\u30c1\u30fc\u30e0\u5185\u306e\u30c9\u30e9\u30b4\u30f3\u30ad\u30e9\u30fc\u306e\u899a\u9192\u6570\u306b\u5fdc\u3058\u3066\u653b\u6483\u529b\u304c\u4e0a\u6607\u3002(1\u500b\u306b\u3064\u304d50%)",
#     "TS_DESC_KR": "2\ud134\uac04 \ud300\ub0b4\uc758 \ub4dc\ub798\uace4 \ud0ac\ub7ec \uac01\uc131 \uac2f\uc218\uc5d0 \ub530\ub77c \uacf5\uaca9\ub825\uc774 \uc0c1\uc2b9 (\uac1c\ub2f9 50%)",
#     "TS_DESC_US": "Increase ATK depending on number of Dragon Killer Awakening Skills on team for 2 turns (50% per each)",
#     "TS_NAME_JP": "\u6e9c\u3081\u65ac\u308a",
#     "TS_NAME_KR": "\u6e9c\u3081\u65ac\u308a",
#     "TS_NAME_US": "\u6e9c\u3081\u65ac\u308a",
#     "TS_SEQ": "12478",
#     "TT_SEQ_1": "0",
#     "TT_SEQ_2": "0",
#     "TURN_MAX": "22",
#     "TURN_MIN": "14",
#     "T_CONDITION": "3"
# }
class PgSkill(PgItem):
    @staticmethod
    def file_name():
        return 'skillList'

    def __init__(self, item):
        super().__init__()
        self.ts_seq = int(item['TS_SEQ'])
        self.name = item['TS_NAME_US']
        self.desc = item['TS_DESC_US']
        self.turn_min = int(item['TURN_MIN'])
        self.turn_max = int(item['TURN_MAX'])

        self.monsters_with_active = []  # PgMonster
        self.monsters_with_leader = []  # PgMonster
        self.monsters_with_awakening = []  # PgMonster

        # str (NA, JP) -> PgMonster
        self.server_skillups = {}

    def key(self):
        return self.ts_seq

    def load(self, database: PgRawDatabase):
        pass


# skillLeaderDataList
#
# PgSkillLeaderData
# 4 pipe delimited fields, each field is a condition
# Slashes separate effects for conditions
# 1: Code 1=HP, 2=ATK, 3=RCV, 4=Reduction
# 2: Multiplier
# 3: Color restriction (coded)
# 4: Type restriction (coded)
# 5: Combo restriction
#
# Reincarnated Izanagi, 4x + 50% for heal cross, 2x atk 2x rcv for god/dragon/balanced
# {
#     "LEADER_DATA": "4/0.5///|2/4///|2/2//6,1,2/|3/2//6,1,2/",
#     "TSTAMP": "1487553365770",
#     "TS_SEQ": "11695"
# },
# Gold Saint, Shion : 4.5X atk when 3+ light combo
# {
#     "LEADER_DATA": "2/4.5///3",
#     "TSTAMP": "1432940060708",
#     "TS_SEQ": "6661"
# },
# Reincarnated Minerva, 3x damage, 2x damage, color resist
# {
#     "LEADER_DATA": "2/3/1//|2/2///|4/0.5/1,4,5//",
#     "TSTAMP": "1475243514648",
#     "TS_SEQ": "10835"
# },
class PgSkillLeaderData(PgItem):
    @staticmethod
    def empty():
        return PgSkillLeaderData({
            'TS_SEQ': '-1',
            'LEADER_DATA': '',
        })

    @staticmethod
    def file_name():
        return 'skillLeaderDataList'

    def __init__(self, item):
        super().__init__()
        self.ts_seq = int(item['TS_SEQ'])  # unique id
        self.leader_data = item['LEADER_DATA']

        hp, atk, rcv, resist = (1.0,) * 4
        for mod in self.leader_data.split('|'):
            if not mod.strip():
                continue
            items = mod.split('/')

            code = items[0]
            mult = float(items[1])
            if code == '1':
                hp *= mult
            if code == '2':
                atk *= mult
            if code == '3':
                rcv *= mult
            if code == '4':
                resist *= mult

        self.hp = hp
        self.atk = atk
        self.rcv = rcv
        self.resist = resist

    def key(self):
        return self.ts_seq

    def load(self, database: PgRawDatabase):
        pass

    def get_data(self):
        return self.hp, self.atk, self.rcv, self.resist


# skillRotationList
# {
#     "MONSTER_NO": "915",
#     "SERVER": "JP",
#     "STATUS": "0",
#     "TSR_SEQ": "2",
#     "TSTAMP": "1481627094573"
# }
class PgSkillRotation(PgItem):
    @staticmethod
    def file_name():
        return 'skillRotationList'

    def __init__(self, item):
        super().__init__()
        self.tsr_seq = int(item['TSR_SEQ'])  # unique id
        self.monster_no = int(item['MONSTER_NO'])
        self.server = normalizeServer(item['SERVER'])  # JP, NA, KR
        # Status seems to be rarely '2'
        self.status = int(item['STATUS'])

    def key(self):
        return self.tsr_seq

    def deleted(self):
        return self.server == 'KR' or self.status != 0  # We don't do KR

    def load(self, database: PgRawDatabase):
        self.monster = database.getMonster(self.monster_no)


# skillRotationListList
# {
#     "ROTATION_DATE": "2016-12-14",
#     "STATUS": "0",
#     "TSRL_SEQ": "960",
#     "TSR_SEQ": "86",
#     "TSTAMP": "1481627993157",
#     "TS_SEQ": "9926"
# }
class PgSkillRotationDated(PgItem):
    @staticmethod
    def file_name():
        return 'skillRotationListList'

    def __init__(self, item):
        super().__init__()
        self.tsrl_seq = int(item['TSRL_SEQ'])  # unique id
        self.tsr_seq = int(item['TSR_SEQ'])  # PgSkillRotation id - Current skillup monster
        self.ts_seq = int(item['TS_SEQ'])  # PGSkill id - Current skill
        self.rotation_date_str = item['ROTATION_DATE']

        self.rotation_date = None
        if len(self.rotation_date_str):
            self.rotation_date = datetime.strptime(self.rotation_date_str, "%Y-%m-%d").date()

    def key(self):
        return self.tsrl_seq

    def load(self, database: PgRawDatabase):
        self.skill = database.getSkill(self.ts_seq)
        self.skill_rotation = database.getSkillRotation(self.tsr_seq)

        if self.skill_rotation:
            self.skill_rotation.monster.rotating_skillups.append(self)


# typeList
# {
#     "ORDER_IDX": "2",
#     "TSTAMP": "1375363406092",
#     "TT_NAME_JP": "\u60aa\u9b54",
#     "TT_NAME_KR": "\uc545\ub9c8",
#     "TT_NAME_US": "Devil",
#     "TT_SEQ": "10"
# },
class PgType(PgItem):
    @staticmethod
    def file_name():
        return 'typeList'

    def __init__(self, item):
        super().__init__()
        self.tt_seq = int(item['TT_SEQ'])  # unique id
        self.name = item['TT_NAME_US']

    def key(self):
        return self.tt_seq

    def load(self, database: PgRawDatabase):
        pass


class PgMonsterDropInfoCombined(object):
    def __init__(self, monster_id, dungeon_monster_drop, dungeon_monster, dungeon):
        self.monster_id = monster_id
        self.dungeon_monster_drop = dungeon_monster_drop
        self.dungeon_monster = dungeon_monster
        self.dungeon = dungeon


# ================================================================================
# PadRem items below
# ================================================================================

class RemType(Enum):
    godfest = 1
    rare = 2
    pal = 3
    unknown1 = 4


class RemRowType(Enum):
    subsection = 0
    divider = 1


# eggTitleList
#       {
#            "DEL_YN": "N",
#            "END_DATE": "2016-10-24 07:59:00",
#            "ORDER_IDX": "0",
#            "SERVER": "US",
#            "SHOW_YN": "Y",
#            "START_DATE": "2016-10-17 08:00:00",
#            "TEC_SEQ": "2",
#            "TET_SEQ": "64",
#            "TSTAMP": "1476490114488",
#            "TYPE": "1"
#        },
class PgEggInstance(PgItem):
    @staticmethod
    def file_name():
        return 'eggTitleList'

    def __init__(self, item):
        super().__init__()
        self.server = normalizeServer(item['SERVER'])
        self.deleted_yn = item['DEL_YN']  # Y, N
        self.show_yn = item['SHOW_YN']  # Y, N
        self.rem_type = RemType(int(item['TEC_SEQ']))  # matches RemType
        self.tet_seq = int(item['TET_SEQ'])  # primary key
        self.row_type = RemRowType(int(item['TYPE']))  # 0-> row with just name, 1-> row with date

        self.order = int(item["ORDER_IDX"])
        self.start_date_str = item['START_DATE']
        self.end_date_str = item['END_DATE']

        self.egg_name_us = None
        self.egg_monsters = []

        tz = pytz.UTC
        self.start_datetime = None
        self.end_datetime = None
        self.open_date_str = None

#         self.pt_date_str = None
        if len(self.start_date_str):
            self.start_datetime = datetime.strptime(
                self.start_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            self.end_datetime = datetime.strptime(
                self.end_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)

            if self.server == 'NA':
                pt_tz_obj = pytz.timezone('America/Los_Angeles')
                self.open_date_str = self.start_datetime.replace(tzinfo=pt_tz_obj).strftime('%m/%d')
            if self.server == 'JP':
                jp_tz_obj = pytz.timezone('Asia/Tokyo')
                self.open_date_str = self.start_datetime.replace(tzinfo=jp_tz_obj).strftime('%m/%d')

    def key(self):
        return self.tet_seq

    def deleted(self):
        return (self.deleted_yn == 'Y' or
                self.show_yn == 'N' or
                self.server == 'KR' or
                self.rem_type in (RemType.pal, RemType.unknown1))

    def load(self, database: PgRawDatabase):
        pass
#         self.monster = database.getMonster(self.monster_no)


# eggMonsterList
#        {
#            "DEL_YN": "Y",
#            "MONSTER_NO": "120",
#            "ORDER_IDX": "1",
#            "TEM_SEQ": "1",
#            "TET_SEQ": "1",
#            "TSTAMP": "1405245537715"
#        },
class PgEggMonster(PgItem):
    @staticmethod
    def file_name():
        return 'eggMonsterList'

    def __init__(self, item):
        super().__init__()
        self.deleted_yn = item['DEL_YN']
        self.monster_no = int(item['MONSTER_NO'])
        self.tem_seq = int(item['TEM_SEQ'])  # primary key
        self.tet_seq = int(item['TET_SEQ'])  # fk to PgEggInstance

    def key(self):
        return self.tem_seq

    def deleted(self):
        return self.deleted_yn == 'Y' or self.monster_no == 0

    def load(self, database: PgRawDatabase):
        self.monster = database.getMonster(self.monster_no)
        self.egg_instance = database.getEggInstance(self.tet_seq)
        if self.egg_instance:
            # For KR stuff we clipped out
            self.egg_instance.egg_monsters.append(self)


# eggTitleNameList
#        {
#            "DEL_YN": "N",
#            "LANGUAGE": "US",
#            "NAME": "Batman Egg",
#            "TETN_SEQ": "183",
#            "TET_SEQ": "64",
#            "TSTAMP": "1441589491425"
#        },
class PgEggName(PgItem):
    @staticmethod
    def file_name():
        return 'eggTitleNameList'

    def __init__(self, item):
        super().__init__()
        self.name = item['NAME']
        self.language = item['LANGUAGE']  # US, JP, KR
        self.deleted_yn = item['DEL_YN']  # Y, N
        self.tetn_seq = int(item['TETN_SEQ'])  # primary key
        self.tet_seq = int(item['TET_SEQ'])  # fk to PgEggInstance

    def key(self):
        return self.tetn_seq

    def deleted(self):
        return self.deleted_yn == 'Y' or self.language != 'US'

    def load(self, database: PgRawDatabase):
        self.egg_instance = database.getEggInstance(self.tet_seq)
        if self.egg_instance:
            # For KR stuff we clipped out
            self.egg_instance.egg_name_us = self


# ================================================================================
# PadEvents items below
# ================================================================================


class EventType(Enum):
    EventTypeWeek = 0
    EventTypeSpecial = 1
    EventTypeSpecialWeek = 2
    EventTypeGuerrilla = 3
    EventTypeGuerrillaNew = 4
    EventTypeEtc = -100


def normalizeServer(server):
    server = server.upper()
    return 'NA' if server == 'US' else server


# {
#     "CLOSE_DATE": "2017-09-01",
#     "CLOSE_HOUR": "19",
#     "CLOSE_MINUTE": "59",
#     "CLOSE_WEEKDAY": "0",
#     "DUNGEON_SEQ": "31",
#     "EVENT_SEQ": "25",
#     "EVENT_TYPE": "-100",
#     "OPEN_DATE": "2017-09-01",
#     "OPEN_HOUR": "08",
#     "OPEN_MINUTE": "00",
#     "OPEN_WEEKDAY": "0",
#     "SCHEDULE_SEQ": "235217",
#     "SERVER": "US",
#     "SERVER_OPEN_DATE": "2017-09-01",
#     "SERVER_OPEN_HOUR": "1",
#     "TEAM_DATA": "0",
#     "TSTAMP": "1504233623450",
#     "URL": ""
# },
class PgScheduledEvent(PgItem):
    @staticmethod
    def file_name():
        return 'scheduleList'

    def __init__(self, item):
        super().__init__()
        self.schedule_seq = int(item['SCHEDULE_SEQ'])

        self.open_timestamp = int(item['OPEN_TIMESTAMP'])
        self.close_timestamp = int(item['CLOSE_TIMESTAMP'])

        self.dungeon_seq = int(item['DUNGEON_SEQ'])
        self.event_seq = int(item['EVENT_SEQ'])
        self.event_type = int(item['EVENT_TYPE'])

        self.server = normalizeServer(item['SERVER'])

        self.team_data = int_or_none(item['TEAM_DATA'])
        self.url = item['URL']

        self.group = None
        if self.team_data is not None:
            if self.event_type == EventType.EventTypeGuerrilla.value:
                self.group = chr(ord('a') + self.team_data).upper()
            elif self.event_type == EventType.EventTypeSpecialWeek.value:
                self.group = ['RED', 'BLUE', 'GREEN'][self.team_data]

        self.open_datetime = datetime.utcfromtimestamp(
            self.open_timestamp).replace(tzinfo=pytz.UTC)
        self.close_datetime = datetime.utcfromtimestamp(
            self.close_timestamp).replace(tzinfo=pytz.UTC)

    def key(self):
        return self.schedule_seq

    def deleted(self):
        return self.server == 'KR'

    def load(self, database: PgRawDatabase):
        self.dungeon = database.getDungeon(self.dungeon_seq)
        self.event = database.getEvent(self.event_seq) if self.event_seq != '0' else None


# {
#     "EVENT_NAME_JP": "\u30b3\u30a4\u30f3 1.5\u500d!",
#     "EVENT_NAME_KR": "\ucf54\uc778 1.5\ubc30!",
#     "EVENT_NAME_US": "Coin x 1.5!",
#     "EVENT_SEQ": "3",
#     "TSTAMP": "1370174967128"
# },
class PgEvent(PgItem):
    @staticmethod
    def file_name():
        return 'eventList'

    def __init__(self, item):
        super().__init__()
        self.event_seq = int(item['EVENT_SEQ'])
        self.name = item['EVENT_NAME_US']

    def key(self):
        return self.event_seq

    def load(self, database: PgRawDatabase):
        pass


def make_roma_subname(name_jp):
    subname = name_jp.replace('＝', '')
    adjusted_subname = ''
    for part in subname.split('・'):
        roma_part = romkan.to_roma(part)
        if part != roma_part and not rpadutils.containsJp(roma_part):
            adjusted_subname += ' ' + roma_part.strip('-')
    return adjusted_subname.strip()


def int_or_none(maybe_int: str):
    return int(maybe_int) if maybe_int else None


def float_or_none(maybe_float: str):
    return float(maybe_float) if maybe_float else None


def empty_index():
    return MonsterIndex(PgRawDatabase(skip_load=True), {}, {}, {})


class MonsterIndex(object):
    def __init__(self, monster_database, nickname_overrides, basename_overrides, panthname_overrides, accept_filter=None):
        # Important not to hold onto anything except IDs here so we don't leak memory
        monster_groups = monster_database.grouped_monsters

        self.attr_short_prefix_map = {
            Attribute.Fire: ['r'],
            Attribute.Water: ['b'],
            Attribute.Wood: ['g'],
            Attribute.Light: ['l'],
            Attribute.Dark: ['d'],
        }
        self.attr_long_prefix_map = {
            Attribute.Fire: ['red', 'fire'],
            Attribute.Water: ['blue', 'water'],
            Attribute.Wood: ['green', 'wood'],
            Attribute.Light: ['light'],
            Attribute.Dark: ['dark'],
        }

        self.series_to_prefix_map = {
            130: ['halloween', 'hw', 'h'],
            136: ['xmas', 'christmas'],
            125: ['summer', 'beach'],
            114: ['school', 'academy', 'gakuen'],
            139: ['new years', 'ny'],
            149: ['wedding', 'bride'],
            154: ['padr'],
            175: ['valentines', 'vday'],
        }

        monster_no_na_to_nicknames = defaultdict(set)
        for nickname, monster_no_na in nickname_overrides.items():
            monster_no_na_to_nicknames[monster_no_na].add(nickname)

        named_monsters = []
        for mg in monster_groups:
            group_basename_overrides = basename_overrides.get(mg.base_monster.monster_no_na, [])
            named_mg = NamedMonsterGroup(mg, group_basename_overrides)
            for monster in mg.members:
                if accept_filter and not accept_filter(monster):
                    continue
                prefixes = self.compute_prefixes(monster, mg)
                extra_nicknames = monster_no_na_to_nicknames[monster.monster_no_na]
                named_monster = NamedMonster(monster, named_mg, prefixes, extra_nicknames)
                named_monsters.append(named_monster)

        # Sort the NamedMonsters into the opposite order we want to accept their nicknames in
        # This order is:
        #  1) High priority first
        #  2) Larger group sizes
        #  3) Minimum ID size in the group
        #  4) Monsters with higher ID values
        def named_monsters_sort(nm: NamedMonster):
            return (not nm.is_low_priority, nm.group_size, -1 *
                    nm.base_monster_no_na, nm.monster_no_na)
        named_monsters.sort(key=named_monsters_sort)
        
        # set up a set of all pantheon names, a set of all pantheon nicknames, and a dictionary of nickname -> full name
        # later we will set up a dictionary of pantheon full name -> monsters
        self.all_pantheon_names = set()
        self.all_pantheon_names.update(panthname_overrides.values())
        
        self.pantheon_nick_to_name = panthname_overrides
        self.pantheon_nick_to_name.update(panthname_overrides)
        
        self.all_pantheon_nicknames = set()
        self.all_pantheon_nicknames.update(panthname_overrides.keys())

        self.all_prefixes = set()
        self.pantheons = defaultdict(set)
        self.all_entries = {}
        self.two_word_entries = {}
        for nm in named_monsters:
            self.all_prefixes.update(nm.prefixes)
            for nickname in nm.final_nicknames:
                self.all_entries[nickname] = nm
            for nickname in nm.final_two_word_nicknames:
                self.two_word_entries[nickname] = nm
            if nm.series:
                for pantheon in self.all_pantheon_names:
                    if pantheon.lower() == nm.series.lower():
                        self.pantheons[pantheon.lower()].add(nm)

        self.all_monsters = named_monsters
        self.all_na_name_to_monsters = {m.name_na.lower(): m for m in named_monsters}
        self.monster_no_na_to_named_monster = {m.monster_no_na: m for m in named_monsters}
        self.monster_no_to_named_monster = {m.monster_no: m for m in named_monsters}

        for nickname, monster_no_na in nickname_overrides.items():
            nm = self.monster_no_na_to_named_monster.get(monster_no_na)
            if nm:
                self.all_entries[nickname] = nm
        

    def init_index(self):
        pass

    def compute_prefixes(self, m: PgMonster, mg: MonsterGroup):
        prefixes = set()

        attr1_short_prefixes = self.attr_short_prefix_map[m.attr1]
        attr1_long_prefixes = self.attr_long_prefix_map[m.attr1]
        prefixes.update(attr1_short_prefixes)
        prefixes.update(attr1_long_prefixes)

        # If no 2nd attribute, use x so we can look those monsters up easier
        attr2_short_prefixes = self.attr_short_prefix_map.get(m.attr2, ['x'])
        for a1 in attr1_short_prefixes:
            for a2 in attr2_short_prefixes:
                prefixes.add(a1 + a2)
                prefixes.add(a1 + '/' + a2)

        # TODO: add prefixes based on type

        # Chibi monsters have the same NA name, except lowercased
        if m.name_na != m.name_jp:
            if m.name_na.lower() == m.name_na:
                prefixes.add('chibi')
        elif 'ミニ' in m.name_jp:
            # Guarding this separately to prevent 'gemini' from triggering (e.g. 2645)
            prefixes.add('chibi')

        lower_name = m.name_na.lower()
        awoken = lower_name.startswith('awoken') or '覚醒' in lower_name
        revo = lower_name.startswith('reincarnated') or '転生' in lower_name
        mega = lower_name.startswith('mega woken') or '極醒' in lower_name
        awoken_or_revo_or_equip_or_mega = awoken or revo or m.is_equip or mega

        # These clauses need to be separate to handle things like 'Awoken Thoth' which are
        # actually Evos but have awoken in the name
        if awoken:
            prefixes.add('a')
            prefixes.add('awoken')

        if revo:
            prefixes.add('revo')
            prefixes.add('reincarnated')

        if mega:
            prefixes.add('mega')
            prefixes.add('mega awoken')
            prefixes.add('awoken')

        # Prefixes for evo type
        if m.cur_evo_type == EvoType.Base:
            prefixes.add('base')
        elif m.cur_evo_type == EvoType.Evo:
            prefixes.add('evo')
        elif m.cur_evo_type == EvoType.UvoAwoken and not awoken_or_revo_or_equip_or_mega:
            prefixes.add('uvo')
            prefixes.add('uevo')
        elif m.cur_evo_type == EvoType.UuvoReincarnated and not awoken_or_revo_or_equip_or_mega:
            prefixes.add('uuvo')
            prefixes.add('uuevo')

        # If any monster in the group is a pixel, add 'nonpixel' to all the versions
        # without pixel in the name. Add 'pixel' as a prefix to the ones with pixel in the name.
        def is_pixel(n):
            n = n.name_na.lower()
            return n.startswith('pixel') or n.startswith('ドット')

        for gm in mg.members:
            if is_pixel(gm):
                prefixes.update(['pixel'] if is_pixel(m) else ['np', 'nonpixel'])
                break

        if m.is_equip:
            prefixes.add('assist')
            prefixes.add('equip')

        # Collab prefixes
        prefixes.update(self.series_to_prefix_map.get(m.series.tsr_seq, []))

        return prefixes

    def find_monster(self, query):
        query = rpadutils.rmdiacritics(query).lower().strip()

        # id search
        if query.isdigit():
            m = self.monster_no_na_to_named_monster.get(int(query))
            if m is None:
                return None, 'Looks like a monster ID but was not found', None
            else:
                return m, None, "ID lookup"
            # special handling for na/jp

        # TODO: need to handle na_only?

        # handle exact nickname match
        if query in self.all_entries:
            return self.all_entries[query], None, "Exact nickname"

        contains_jp = rpadutils.containsJp(query)
        if len(query) < 2 and contains_jp:
            return None, 'Japanese queries must be at least 2 characters', None
        elif len(query) < 4 and not contains_jp:
            return None, 'Your query must be at least 4 letters', None

        # TODO: this should be a length-limited priority queue
        matches = set()
        # prefix search for nicknames, space-preceeded, take max id
        for nickname, m in self.all_entries.items():
            if nickname.startswith(query + ' '):
                matches.add(m)
        if len(matches):
            return self.pickBestMonster(matches), None, "Space nickname prefix, max of {}".format(len(matches))

        # prefix search for nicknames, take max id
        for nickname, m in self.all_entries.items():
            if nickname.startswith(query):
                matches.add(m)
        if len(matches):
            all_names = ",".join(map(lambda x: x.name_na, matches))
            return self.pickBestMonster(matches), None, "Nickname prefix, max of {}, matches=({})".format(len(matches), all_names)

        # prefix search for full name, take max id
        for nickname, m in self.all_entries.items():
            if (m.name_na.lower().startswith(query) or m.name_jp.lower().startswith(query)):
                matches.add(m)
        if len(matches):
            return self.pickBestMonster(matches), None, "Full name, max of {}".format(len(matches))

        # for nicknames with 2 names, prefix search 2nd word, take max id
        if query in self.two_word_entries:
            return self.two_word_entries[query], None, "Second-word nickname prefix, max of {}".format(len(matches))

        # TODO: refactor 2nd search characteristcs for 2nd word

        # full name contains on nickname, take max id
        for nickname, m in self.all_entries.items():
            if (query in m.name_na.lower() or query in m.name_jp.lower()):
                matches.add(m)
        if len(matches):
            return self.pickBestMonster(matches), None, 'Full name match on nickname, max of {}'.format(len(matches))

        # full name contains on full monster list, take max id

        for m in self.all_monsters:
            if (query in m.name_na.lower() or query in m.name_jp.lower()):
                matches.add(m)
        if len(matches):
            return self.pickBestMonster(matches), None, 'Full name match on full list, max of {}'.format(len(matches))

        # No decent matches. Try near hits on nickname instead
        matches = difflib.get_close_matches(query, self.all_entries.keys(), n=1, cutoff=.8)
        if len(matches):
            match = matches[0]
            return self.all_entries[match], None, 'Close nickname match ({})'.format(match)

        # Still no decent matches. Try near hits on full name instead
        matches = difflib.get_close_matches(
            query, self.all_na_name_to_monsters.keys(), n=1, cutoff=.9)
        if len(matches):
            match = matches[0]
            return self.all_na_name_to_monsters[match], None, 'Close name match ({})'.format(match)

        # couldn't find anything
        return None, "Could not find a match for: " + query, None
    
    
    def find_monster2(self, query):
        """Search with alternative method for resolving prefixes.
        
        Implements the lookup for id2, where you are allowed to specify multiple prefixes for a card.
        All prefixes are required to be exactly matched by the card.
        Follows a similar logic to the regular id but after each check, will remove any potential match that doesn't
        contain every single specified prefix.
        """
        query = rpadutils.rmdiacritics(query).lower().strip()
        # id search
        if query.isdigit():
            m = self.monster_no_na_to_named_monster.get(int(query))
            if m is None:
                return None, 'Looks like a monster ID but was not found', None
            else:
                return m, None, "ID lookup"
        
        # handle exact nickname match
        if query in self.all_entries:
            return self.all_entries[query], None, "Exact nickname"
    
        contains_jp = rpadutils.containsJp(query)
        if len(query) < 2 and contains_jp:
            return None, 'Japanese queries must be at least 2 characters', None
        elif len(query) < 4 and not contains_jp:
            return None, 'Your query must be at least 4 letters', None

        # we want to look up only the main part of the query, and then verify that each result has the prefixes
        # so break up the query into an array of prefixes, and a string (new_query) that will be the lookup
        query_prefixes = []
        parts_of_query = query.split()
        new_query = ''
        for i, part in enumerate(parts_of_query):
            if part in self.all_prefixes:
                query_prefixes.append(part)
            else:
                new_query = ' '.join(parts_of_query[i:])
                break
        
        # if we don't have any prefixes, then default to using the regular id lookup
        if len(query_prefixes) < 1:
            return self.find_monster(query)
        
        matches = PotentialMatches()
        
        # first try to get matches from nicknames
        for nickname, m in self.all_entries.items():
            if new_query in nickname:
                matches.add(m)
        matches.remove_potential_matches_without_all_prefixes(query_prefixes)
        
        # if we don't have any candidates yet, pick a new method
        if not matches.length():
            # try matching on exact names next
            for nickname, m in self.all_na_name_to_monsters.items():
                if new_query in m.name_na.lower() or new_query in m.name_jp.lower():
                    matches.add(m)
            matches.remove_potential_matches_without_all_prefixes(query_prefixes)
        
        # check for exact match on pantheon name but only if needed
        if not matches.length():
            for pantheon in self.all_pantheon_nicknames:
                if new_query == pantheon.lower():
                    matches.get_monsters_from_potential_pantheon_match(pantheon, self.pantheon_nick_to_name, self.pantheons)
            matches.remove_potential_matches_without_all_prefixes(query_prefixes)

        # check for any match on pantheon name, again but only if needed
        if not matches.length():
            for pantheon in self.all_pantheon_nicknames:
                if new_query in pantheon.lower():
                    matches.get_monsters_from_potential_pantheon_match(pantheon, self.pantheon_nick_to_name, self.pantheons)
            matches.remove_potential_matches_without_all_prefixes(query_prefixes)
        
        if matches.length():
            return matches.pick_best_monster(), None, None
        return None, "Could not find a match for: " + query, None
    
    def pickBestMonster(self, named_monster_list):
        return max(named_monster_list, key=lambda x: (not x.is_low_priority, x.rarity, x.monster_no_na))

class PotentialMatches(object):
    def __init__(self):
        self.match_list = set()
    
    def add(self, m):
        self.match_list.add(m)
    
    def update(self, monster_list):
        self.match_list.update(monster_list)
    
    def length(self):
        return len(self.match_list)
    
    def remove_potential_matches_without_all_prefixes(self, query_prefixes):
        to_remove = set()
        for m in self.match_list:
            for prefix in query_prefixes:
                if prefix not in m.prefixes:
                    to_remove.add(m)
                    break
        self.match_list.difference_update(to_remove)
    
    def get_monsters_from_potential_pantheon_match(self, pantheon, pantheon_nick_to_name, pantheons):
        full_name = pantheon_nick_to_name[pantheon]
        self.update(pantheons[full_name])
    
    def pick_best_monster(self):
        return max(self.match_list, key=lambda x: (not x.is_low_priority, x.rarity, x.monster_no_na))
    

class NamedMonsterGroup(object):
    def __init__(self, monster_group: MonsterGroup, basename_overrides: list):
        self.is_low_priority = (
            self._is_low_priority_monster(monster_group.base_monster)
            or self._is_low_priority_group(monster_group))

        monsters = monster_group.members
        self.group_size = len(monsters)
        self.base_monster_no = monster_group.base_monster.monster_no
        self.base_monster_no_na = monster_group.base_monster.monster_no_na

        self.monster_no_to_basename = {
            m.monster_no: self._compute_monster_basename(m) for m in monsters
        }

        self.computed_basename = self._compute_group_basename(monsters)
        self.computed_basenames = set([self.computed_basename])
        if '-' in self.computed_basename:
            self.computed_basenames.add(self.computed_basename.replace('-', ' '))

        self.basenames = basename_overrides or self.computed_basenames

    def _compute_monster_basename(self, m: PgMonster):
        basename = m.name_na.lower()
        if ',' in basename:
            name_parts = basename.split(',')
            if name_parts[1].strip().startswith('the '):
                # handle names like 'xxx, the yyy' where xxx is the name
                basename = name_parts[0]
            else:
                # otherwise, grab the chunk after the last comma
                basename = name_parts[-1]

        for x in ['awoken', 'reincarnated']:
            if basename.startswith(x):
                basename = basename.replace(x, '')

        # Fix for DC collab garbage
        basename = basename.replace('(comics)', '')
        basename = basename.replace('(film)', '')

        return basename.strip()

    def _compute_group_basename(self, monsters):
        """Computes the basename for a group of monsters.

        Prefer a basename with the largest count across the group. If all the
        groups have equal size, prefer the lowest monster number basename.
        This monster in general has better names, particularly when all the
        names are unique, e.g. for male/female hunters."""
        def count_and_id(): return [0, 0]
        basename_to_info = defaultdict(count_and_id)

        for m in monsters:
            basename = self.monster_no_to_basename[m.monster_no]
            entry = basename_to_info[basename]
            entry[0] += 1
            entry[1] = max(entry[1], m.monster_no)

        entries = [[count_id[0], -1 * count_id[1], bn] for bn, count_id in basename_to_info.items()]
        return max(entries)[2]

    def _is_low_priority_monster(self, m: PgMonster):
        lp_types = ['evolve', 'enhance', 'protected', 'awoken', 'vendor']
        lp_substrings = ['tamadra']
        lp_min_rarity = 2
        name = m.name_na.lower()

        failed_type = m.type1.lower() in lp_types
        failed_ss = any([x in name for x in lp_substrings])
        failed_rarity = m.rarity < lp_min_rarity
        failed_chibi = name == m.name_na and m.name_na != m.name_jp
        failed_equip = m.is_equip
        return failed_type or failed_ss or failed_rarity or failed_chibi or failed_equip

    def _is_low_priority_group(self, mg: MonsterGroup):
        lp_grp_min_rarity = 5
        max_rarity = max(m.rarity for m in mg.members)
        failed_max_rarity = max_rarity < lp_grp_min_rarity
        return failed_max_rarity


class NamedMonster(object):
    def __init__(self, monster: PgMonster, monster_group: NamedMonsterGroup, prefixes: set, extra_nicknames: set):
        # Must not hold onto monster or monster_group!

        # Hold on to the IDs instead
        self.monster_no = monster.monster_no
        self.monster_no_na = monster.monster_no_na
        self.monster_no_jp = monster.monster_no_jp

        # ID of the root of the tree for this monster
        self.base_monster_no = monster_group.base_monster_no
        self.base_monster_no_na = monster_group.base_monster_no_na

        # This stuff is important for nickname generation
        self.group_basenames = monster_group.basenames
        self.prefixes = prefixes
        
        # Pantheon
        self.series = monster.series.name if monster.series else None

        # Data used to determine how to rank the nicknames
        self.is_low_priority = monster_group.is_low_priority or monster.is_equip
        self.group_size = monster_group.group_size
        self.rarity = monster.rarity

        # Used in fallback searches
        self.name_na = monster.name_na
        self.name_jp = monster.name_jp

        # These are just extra metadata
        self.monster_basename = monster_group.monster_no_to_basename[self.monster_no]
        self.group_computed_basename = monster_group.computed_basename
        self.extra_nicknames = extra_nicknames

        # Compute any extra prefixes
        if self.monster_basename in ('ana', 'ace'):
            self.prefixes.add(self.monster_basename)

        # Compute extra basenames by checking for two-word basenames and using the second half
        self.two_word_basenames = set()
        for basename in self.group_basenames:
            basename_words = basename.split(' ')
            if len(basename_words) == 2:
                self.two_word_basenames.add(basename_words[1])

        # The primary result nicknames
        self.final_nicknames = set()
        # Set the configured override nicknames
        self.final_nicknames.update(self.extra_nicknames)
        # Set the roma subname for JP monsters
        if monster.roma_subname:
            self.final_nicknames.add(monster.roma_subname)

        # For each basename, add nicknames
        for basename in self.group_basenames:
            # Add the basename directly
            self.final_nicknames.add(basename)
            # Add the prefix plus basename, and the prefix with a space between basename
            for prefix in self.prefixes:
                self.final_nicknames.add(prefix + basename)
                self.final_nicknames.add(prefix + ' ' + basename)

        self.final_two_word_nicknames = set()
        # Slightly different process for two-word basenames. Does this make sense? Who knows.
        for basename in self.two_word_basenames:
            self.final_two_word_nicknames.add(basename)
            # Add the prefix plus basename, and the prefix with a space between basename
            for prefix in self.prefixes:
                self.final_two_word_nicknames.add(prefix + basename)
                self.final_two_word_nicknames.add(prefix + ' ' + basename)

def compute_killers(*types):
    if 'Balance' in types:
        return ['Any']
    killers = set()
    for t in types:
        killers.update(type_to_killers_map.get(t, []))
    return sorted(killers)


type_to_killers_map = {
    'God': ['Devil'],
    'Devil': ['God'],
    'Machine': ['God', 'Balance'],
    'Dragon': ['Machine', 'Healer'],
    'Physical': ['Machine', 'Healer'],
    'Attacker': ['Devil', 'Physical'],
    'Healer': ['Dragon', 'Attacker'],
}
