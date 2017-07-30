"""
Provides access to PadGuide data.

Loads every PadGuide related JSON into a simple data structure, and then
combines them into a an in-memory interconnected database.

Don't hold on to any of the dastructures exported from here, or the
entire database could be leaked when the module is reloaded.
"""
from datetime import datetime
from datetime import timedelta
from enum import Enum
import re

import discord
from discord.ext import commands
import pytz
import romkan
import unidecode

from . import rpadutils
from .utils.cog_settings import CogSettings
from .utils.dataIO import dataIO


# from .rpadutils import *
DUMMY_FILE_PATTERN = 'data/padguide2/{}.dummy'
JSON_FILE_PATTERN = 'data/padguide2/{}.json'


class PadGuide2(object):
    def __init__(self, bot):
        self.bot = bot
        self.settings = PadGuide2Settings("padguide2")

        self._general_types = [
            PgAttribute,
            PgAwakening,
            PgDungeon,
            PgDungeonMonsterDrop,
            PgDungeonMonster,
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
            PgType,
        ]

        self._download_files()
        self.database = PgRawDatabase()

    def _download_files(self):
        # twelve hours expiry
        general_dummy_file = DUMMY_FILE_PATTERN.format('general')
        general_expiry_secs = 12 * 60 * 60
        if not rpadutils.checkPadguideCacheFile(general_dummy_file, general_expiry_secs):
            return

        # Need to add something that downloads if missing
        for type in self._general_types:
            file_name = type.file_name()
            result_file = JSON_FILE_PATTERN.format(file_name)
            rpadutils.makeCachedPadguideRequest2(file_name, result_file)


class PadGuide2Settings(CogSettings):
    def make_default_settings(self):
        config = {
        }
        return config


def setup(bot):
    n = PadGuide2(bot)
    bot.add_cog(n)


class PgRawDatabase(object):
    def __init__(self):
        self._all_pg_items = []

        # Load raw data items into id->value maps
        self._attribute_map = self._load(PgAttribute)
        self._awakening_map = self._load(PgAwakening)
        self._dungeon_map = self._load(PgDungeon)
        self._dungeon_monster_drop_map = self._load(PgDungeonMonsterDrop)
        self._dungeon_monster_map = self._load(PgDungeonMonster)
        self._evolution_map = self._load(PgEvolution)
        self._evolution_material_map = self._load(PgEvolutionMaterial)
        self._monster_map = self._load(PgMonster)
        self._monster_add_info_map = self._load(PgMonsterAddInfo)
        self._monster_info_map = self._load(PgMonsterInfo)
        self._monster_price_map = self._load(PgMonsterPrice)
        self._series_map = self._load(PgSeries)
        self._skill_leader_data_map = self._load(PgSkillLeaderData)
        self._skill_map = self._load(PgSkill)
        self._skill_rotation_map = self._load(PgSkillRotation)
        self._skill_rotation_dated_map = self._load(PgSkillRotationDated)
        self._type_map = self._load(PgType)

        for i in self._all_pg_items:
            self._ensure_loaded(i)

    def _load(self, itemtype):
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

    def getAttributeEnum(self, ta_seq: int):
        attr = self._ensure_loaded(self._attribute_map.get(ta_seq))
        return attr.value if attr else None

    def getAwakening(self, tma_seq: int):
        return self._ensure_loaded(self._awakening_map.get(tma_seq))

    def getDungeon(self, dungeon_seq: int):
        return self._ensure_loaded(self._dungeon_map.get(dungeon_seq))

    def getDungeonMonsterDrop(self, tdmd_seq: int):
        return self._ensure_loaded(self._dungeon_monster_drop_map.get(tdmd_seq))

    def getDungeonMonster(self, tdm_seq: int):
        return self._ensure_loaded(self._dungeon_monster_map.get(tdm_seq))

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

    def getSkill(self, ts_seq: int):
        return self._ensure_loaded(self._skill_map.get(ts_seq))

    def getSkillLeaderData(self, ts_seq: int):
        return self._ensure_loaded(self._skill_leader_data_map.get(ts_seq))

    def getSkillRotation(self, tsr_seq: int):
        return self._ensure_loaded(self._skill_rotation_map.get(tsr_seq))

    def getSkillRotationDated(self, tsrl_seq: int):
        return self._ensure_loaded(self._skill_rotation_dated_map.get(tsrl_seq))

    def getTypeName(self, tt_seq: int):
        type = self._ensure_loaded(self._type_map.get(tt_seq))
        return type.name if type else None


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
            self.load(database)

        return self

    def load(self, database: PgRawDatabase):
        """Override to inject dependencies."""
        raise NotImplementedError()


class Attribute(Enum):
    """Standard 5 PAD colors in enum form. Values correspond to PadGuide values."""
    Fire = 1
    Water = 2
    Wood = 3
    Light = 4
    Dark = 5


# attributeList.jsp
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
        return 'attributeList.jsp'

    def __init__(self, item):
        super().__init__()
        self.ta_seq = int(item['TA_SEQ'])  # unique id
        self.name = item['TA_NAME_US']

        self.value = Attribute(self.ta_seq)

    def key(self):
        return self.ta_seq

    def load(self, database: PgRawDatabase):
        pass


# awokenSkillList.jsp
# {
#     "DEL_YN": "N",
#     "MONSTER_NO": "661",
#     "ORDER_IDX": "1",
#     "TMA_SEQ": "1",
#     "TSTAMP": "1380587210665",
#     "TS_SEQ": "2769"
# },
class PgAwakening(PgItem):
    @staticmethod
    def file_name():
        return 'awokenSkillList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tma_seq = int(item['TMA_SEQ'])  # unique id
        self.ts_seq = int(item['TS_SEQ'])  # PgSkill id - awakening info
        self.deleted_yn = item['DEL_YN']  # Either Y(discard) or N.
        self.monster_no = int(item['MONSTER_NO'])  # PgMonster id - monster this belongs to
        self.order = int(item['ORDER_IDX'])  # display order

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


# dungeonList.jsp
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
        return 'dungeonList.jsp'

    def __init__(self, item):
        super().__init__()
        self.dungeon_seq = int(item['DUNGEON_SEQ'])
        self.type = DungeonType(int(item['DUNGEON_TYPE']))
        self.name = item['NAME_US']
#         self.tdt_seq = int(item['TDT_SEQ']) # What is this used for?
        self.show_yn = item["SHOW_YN"]

    def key(self):
        return self.dungeon_seq

    def deleted(self):
        # TODO: Is show y/n the same as deleted?
        return False

    def load(self, database: PgRawDatabase):
        pass


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
        return 'dungeonMonsterDropList.jsp'

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


# dungeonMonsterList.jsp
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
        return 'dungeonMonsterList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tdm_seq = int(item['TDM_SEQ'])  # unique id
        self.drop_monster_no = int(item['DROP_NO'])  # PgMonster unique id
        self.monster_no = int(item['MONSTER_NO'])  # PgMonster unique id
        self.dungeon_seq = int(item['DUNGEON_SEQ'])  # PgDungeon uniqueId
        self.tsd_seq = int(item['TSD_SEQ'])  # ??

    def key(self):
        return self.tdm_seq

    def load(self, database: PgRawDatabase):
        self.drop_monster = database.getMonster(self.drop_monster_no)
        self.monster = database.getMonster(self.monster_no)
        self.dungeon = database.getDungeon(self.dungeon_seq)

        if self.drop_monster:
            self.drop_monster.drop_dungeons.append(self.dungeon)


class EvoType(Enum):
    """Evo types supported by PadGuide. Numbers correspond to their id values."""
    Base = -1  # Represents monsters who didn't require evo
    Evo = 0
    UvoAwoken = 1
    UuvoReincarnated = 2


# evolutionList.jsp
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
        return 'evolutionList.jsp'

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

        self.to_monster.cur_evo_type = self.evo_type
        self.to_monster.evo_from = self.from_monster
        self.from_monster.evo_to.append(self.to_monster)


# evoMaterialList.jsp
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
        return 'evoMaterialList.jsp'

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

        if self.evolution is None:
            # Really rare and unusual bug
            return

        target_monster = self.evolution.to_monster
        target_monster.material_for.append(self.fodder_monster)
        self.fodder_monster.material_of.append(target_monster)


# monsterAddInfoList.jsp
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
        return 'monsterAddInfoList.jsp'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.sub_type = int(item['SUB_TYPE'])
        self.extra_val_1 = int_or_none(item['EXTRA_VAL1'])

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        pass


# monsterInfoList.jsp
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
        return 'monsterInfoList.jsp'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.on_na = item['ON_US'] == '1'
        self.tsr_seq = int_or_none(item['TSR_SEQ'])  # PgSeries id
        self.in_pem = item['PAL_EGG'] == '1'
        self.in_rem = item['RARE_EGG'] == '1'

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        self.series = database.getSeries(self.tsr_seq)


# monsterList.jsp
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
        return 'monsterList.jsp'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.monster_no_na = int(item['MONSTER_NO_US'])
        self.monster_no_jp = int(item['MONSTER_NO_JP'])
        self.hp = int(item['HP_MAX'])
        self.atk = int(item['ATK_MAX'])
        self.rcv = int(item['RCV_MAX'])
        self.ts_seq_active = int_or_none(item['TS_SEQ_SKILL'])
        self.ts_seq_leader = int_or_none(item['TS_SEQ_LEADER'])
        self.rarity = int(item['RARITY'])
        self.cost = int(item['COST'])
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

        self.cur_evo_type = EvoType.Base
        self.evo_to = []
        self.evo_from = None

        self.material_for = []
        self.material_of = []

        self.awakenings = []
        self.drop_dungeons = []

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        self.active_skill = database.getSkill(self.ts_seq_active)
        self.leader_skill = database.getSkill(self.ts_seq_leader)
        self.leader_skill_data = database.getSkillLeaderData(self.ts_seq_leader)

        self.attr1 = database.getAttributeEnum(self.ta_seq_1)
        self.attr2 = database.getAttributeEnum(self.ta_seq_2)

        self.type1 = database.getTypeName(self.tt_seq_1)
        self.type2 = database.getTypeName(self.tt_seq_2)
        self.type3 = None

        assist_setting = None
        monster_add_info = database.getMonsterAddInfo(self.monster_no)
        if monster_add_info:
            self.type3 = database.getTypeName(monster_add_info.sub_type)
            assist_setting = monster_add_info.extra_val_1

        monster_info = database.getMonsterInfo(self.monster_no)
        self.on_na = monster_info.on_na
        self.series_id = monster_info.tsr_seq
        self.is_gfe = self.series_id == 34
        self.in_pem = monster_info.in_pem
        self.in_rem = monster_info.in_rem
        self.pem_evo = self.in_pem
        self.rem_evo = self.in_rem

        monster_price = database.getMonsterPrice(self.monster_no)
        self.buy_mp = monster_price.buy_mp
        self.in_mpshop = self.buy_mp > 0
        self.sell_mp = monster_price.sell_mp

        if assist_setting == 1:
            self.is_inheritable = True
        elif assist_setting == 2:
            self.is_inheritable = False
        else:
            has_awakenings = len(self.awakenings) > 0
            self.is_inheritable = has_awakenings and self.rarity >= 5 and self.sell_mp > 3000


# monsterPriceList.jsp
# {
#     "BUY_PRICE": "0",
#     "MONSTER_NO": "3577",
#     "SELL_PRICE": "99",
#     "TSTAMP": "1492101772974"
# }
class PgMonsterPrice(PgItem):
    @staticmethod
    def file_name():
        return 'monsterPriceList.jsp'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.buy_mp = int(item['BUY_PRICE'])
        self.sell_mp = int(item['SELL_PRICE'])

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        pass


# seriesList.jsp
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
        return 'seriesList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tsr_seq = int(item['TSR_SEQ'])
        self.name = item['NAME_US']
        self.deleted_yn = item['DEL_YN']  # Either Y(discard) or N.

    def key(self):
        return self.tsr_seq

    def deleted(self):
        return self.deleted_yn == 'Y'

    def load(self, database: PgRawDatabase):
        pass


# skillList.jsp
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
        return 'skillList.jsp'

    def __init__(self, item):
        super().__init__()
        self.ts_seq = int(item['TS_SEQ'])
        self.name = item['TS_NAME_US']
        self.desc = item['TS_DESC_US']
        self.turn_min = int(item['TURN_MIN'])
        self.turn_max = int(item['TURN_MAX'])

    def key(self):
        return self.ts_seq

    def load(self, database: PgRawDatabase):
        pass


# skillLeaderDataList.jsp
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
    def file_name():
        return 'skillLeaderDataList.jsp'

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


# skillRotationList.jsp
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
        return 'skillRotationList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tsr_seq = int(item['TSR_SEQ'])  # unique id
        self.monster_no = int(item['MONSTER_NO'])
        self.server = item['SERVER']  # JP, NA, KR
        self.status = item['STATUS']
        # TODO: what does status do?

    def key(self):
        return self.tsr_seq

    def deleted(self):
        return self.server == 'KR'  # We don't do KR

    def load(self, database: PgRawDatabase):
        self.monster = database.getMonster(self.monster_no)


# skillRotationListList.jsp
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
        return 'skillRotationListList.jsp'

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


class PgMergedRotation:
    def __init__(self, rotation, dated_rotation):
        self.monster_id = rotation.monster_id
        self.server = rotation.server
        self.rotation_date = dated_rotation.rotation_date
        self.active_id = dated_rotation.active_id

        self.resolved_monster = None  # The monster that does the skillup
        self.resolved_active = None  # The skill for this server


# typeList.jsp
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
        return 'typeList.jsp'

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
# Items below are deferred (padrem, padevents)
#
#
#
#
# ================================================================================

class RemType(Enum):
    godfest = '1'
    rare = '2'
    pal = '3'
    unknown1 = '4'


class RemRowType(Enum):
    subsection = '0'
    divider = '1'


# eggTitleList.jsp
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
        return 'attributeList.jsp'

    def __init__(self, item):
        self.server = normalizeServer(item['SERVER'])
        self.delete = item['DEL_YN']  # Y, N
        self.show = item['SHOW_YN']  # Y, N
        self.rem_type = RemType(item['TEC_SEQ'])  # matches RemType
        self.egg_id = item['TET_SEQ']  # primary key
        self.row_type = RemRowType(item['TYPE'])  # 0-> row with just name, 1-> row with date

        self.order = int(item["ORDER_IDX"])
        self.start_date_str = item['START_DATE']
        self.end_date_str = item['END_DATE']

        tz = pytz.UTC
        self.start_datetime = None
        self.end_datetime = None
        self.open_date_str = None

        self.pt_date_str = None
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


# eggTitleNameList.jsp
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
        return 'attributeList.jsp'

    def __init__(self, item):
        self.name = item['NAME']
        self.language = item['LANGUAGE']  # US, JP, KR
        self.delete = item['DEL_YN']  # Y, N
        self.primary_id = item['TETN_SEQ']  # primary key
        self.egg_id = item['TET_SEQ']  # fk to PgEggInstance


def makeBlankEggName(egg_id):
    return PgEggName({
        'NAME': '',
        'LANGUAGE': 'US',
        'DEL_YN': 'N',
        'TETN_SEQ': '',
        'TET_SEQ': egg_id
    })

# eggMonsterList.jsp
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
        return 'attributeList.jsp'

    def __init__(self, item):
        self.delete = item['DEL_YN']
        self.monster_id = item['MONSTER_NO']
        self.tem_seq = item['TEM_SEQ']  # primary key
        self.egg_id = item['TET_SEQ']  # fk to PgEggInstance

    def key(self):
        return self.tem_seq


TIME_FMT = """%a %b %d %H:%M:%S %Y"""


class EventType(Enum):
    EventTypeWeek = 0
    EventTypeSpecial = 1
    EventTypeSpecialWeek = 2
    EventTypeGuerrilla = 3
    EventTypeGuerrillaNew = 4
    EventTypeEtc = -100


class DungeonType(Enum):
    Unknown = -1
    Normal = 0
    CoinDailyOther = 1
    Technical = 2
    Etc = 3


class TdtType(Enum):
    Normal = 0
    SpecialOther = 1
    Technical = 2
    Weekly = 2
    Descended = 3


def fmtTime(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def fmtTimeShort(dt):
    return dt.strftime("%H:%M")


def fmtHrsMins(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return '{:2}h {:2}m'.format(int(hours), int(minutes))


def fmtDaysHrsMinsShort(sec):
    days = sec // 86400
    sec -= 86400 * days
    hours = sec // 3600
    sec -= 3600 * hours
    minutes = sec // 60

    if days > 0:
        return '{:2}d {:2}h'.format(int(days), int(hours))
    elif hours > 0:
        return '{:2}h {:2}m'.format(int(hours), int(minutes))
    else:
        return '{:2}m'.format(int(minutes))


def normalizeServer(server):
    server = server.upper()
    return 'NA' if server == 'US' else server


def isEventWanted(event):
    name = event.nameAndModifier().lower()
    if 'castle of satan' in name:
        # eliminate things like : TAMADRA Invades in [Castle of Satan][Castle of Satan in the Abyss]
        return False

    return True


def cleanDungeonNames(name):
    if 'tamadra invades in some tech' in name.lower():
        return 'Latents invades some Techs & 20x +Eggs'
    if '1.5x Bonus Pal Point in multiplay' in name:
        name = '[Descends] 1.5x Pal Points in multiplay'
    name = name.replace('No Continues', 'No Cont')
    name = name.replace('No Continue', 'No Cont')
    name = name.replace('Some Limited Time Dungeons', 'Some Guerrillas')
    name = name.replace('are added in', 'in')
    name = name.replace('!', '')
    name = name.replace('Dragon Infestation', 'Dragons')
    name = name.replace(' Infestation', 's')
    name = name.replace('Daily Descended Dungeon', 'Daily Descends')
    name = name.replace('Chance for ', '')
    name = name.replace('Jewel of the Spirit', 'Spirit Jewel')
    name = name.replace(' & ', '/')
    name = name.replace(' / ', '/')
    name = name.replace('PAD Radar', 'PADR')
    name = name.replace('in normal dungeons', 'in normals')
    name = name.replace('Selected ', 'Some ')
    name = name.replace('Enhanced ', 'Enh ')
    name = name.replace('All Att. Req.', 'All Att.')
    name = name.replace('Extreme King Metal Dragon', 'Extreme KMD')
    name = name.replace('Golden Mound-Tricolor [Fr/Wt/Wd Only]', 'Golden Mound')
    name = name.replace('Gods-Awakening Materials Descended', "Awoken Mats")
    name = name.replace('Orb move time 4 sec', '4s move time')
    name = name.replace('Awakening Materials Descended', 'Awkn Mats')
    name = name.replace("Star Treasure Thieves' Den", 'STTD')
    name = name.replace('Ruins of the Star Vault', 'Star Vault')
    return name


class PgEventList(PgItem):
    def __init__(self, event_list):
        self.event_list = event_list

    def withFunc(self, func, exclude=False):
        if exclude:
            return PgEventList(list(itertools.filterfalse(func, self.event_list)))
        else:
            return PgEventList(list(filter(func, self.event_list)))

    def withServer(self, server):
        return self.withFunc(lambda e: e.server == normalizeServer(server))

    def withType(self, event_type):
        return self.withFunc(lambda e: e.event_type == event_type)

    def withDungeonType(self, dungeon_type, exclude=False):
        return self.withFunc(lambda e: e.dungeon_type == dungeon_type, exclude)

    def withNameContains(self, name, exclude=False):
        return self.withFunc(lambda e: name.lower() in e.dungeon_name.lower(), exclude)

    def excludeUnwantedEvents(self):
        return self.withFunc(isEventWanted)

    def items(self):
        return self.event_list

    def startedOnly(self):
        return self.withFunc(lambda e: e.isStarted())

    def pendingOnly(self):
        return self.withFunc(lambda e: e.isPending())

    def activeOnly(self):
        return self.withFunc(lambda e: e.isActive())

    def availableOnly(self):
        return self.withFunc(lambda e: e.isAvailable())

    def itemsByOpenTime(self, reverse=False):
        return list(sorted(self.event_list, key=(lambda e: (e.open_datetime, e.dungeon_name)), reverse=reverse))

    def itemsByCloseTime(self, reverse=False):
        return list(sorted(self.event_list, key=(lambda e: (e.close_datetime, e.dungeon_name)), reverse=reverse))


class PgEvent(PgItem):
    @staticmethod
    def file_name():
        return 'attributeList.jsp'

    def __init__(self, item, ignore_bad=False):
        if item is None and ignore_bad:
            return
        self.server = normalizeServer(item['SERVER'])
        self.dungeon_code = item['DUNGEON_SEQ']
        self.dungeon_name = 'Unknown(' + self.dungeon_code + ')'
        self.dungeon_type = DungeonType.Unknown
        self.event_type = EventType(int(item['EVENT_TYPE']))
        self.event_seq = item['EVENT_SEQ']
        self.event_modifier = ''
        self.uid = item['SCHEDULE_SEQ']

        team_data = item['TEAM_DATA']
        self.group = ''
        if self.event_type in (EventType.EventTypeGuerrilla, EventType.EventTypeGuerrillaNew) and team_data != '':
            self.group = chr(ord('a') + int(team_data)).upper()

        tz = pytz.UTC
        open_time_str = item['OPEN_DATE'] + " " + item['OPEN_HOUR'] + ":" + item['OPEN_MINUTE']
        close_time_strstr = item['CLOSE_DATE'] + " " + \
            item['CLOSE_HOUR'] + ":" + item['CLOSE_MINUTE']

        self.open_datetime = datetime.strptime(open_time_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        self.close_datetime = datetime.strptime(
            close_time_strstr, "%Y-%m-%d %H:%M").replace(tzinfo=tz)

    def updateDungeonName(self, dungeon_seq_map):
        if self.dungeon_code in dungeon_seq_map:
            dungeon = dungeon_seq_map[self.dungeon_code]
            self.dungeon_name = dungeon.name
            self.dungeon_type = dungeon.type

    def updateEventModifier(self, event_modifier_map):
        if self.event_seq in event_modifier_map:
            self.event_modifier = event_modifier_map[self.event_seq].name

    def isForNormal(self):
        return self.dungeon_type == '0'

    def nameAndModifier(self):
        output = self.name()
        if self.event_modifier != '':
            output += ', ' + self.event_modifier.replace('!', '').replace(' ', '')
        return output

    def name(self):
        output = cleanDungeonNames(self.dungeon_name)
        return output

    def tostr(self):
        return fmtTime(self.open_datetime) + "," + fmtTime(self.close_datetime) + "," + self.group + "," + self.dungeon_code + "," + self.event_type + "," + self.event_seq

    def startPst(self):
        tz = pytz.timezone('US/Pacific')
        return self.open_datetime.astimezone(tz)

    def startEst(self):
        tz = pytz.timezone('US/Eastern')
        return self.open_datetime.astimezone(tz)

    def isStarted(self):
        now = datetime.now(pytz.utc)
        delta_open = self.open_datetime - now
        return delta_open.total_seconds() <= 0

    def isFinished(self):
        now = datetime.now(pytz.utc)
        delta_close = self.close_datetime - now
        return delta_close.total_seconds() <= 0

    def isActive(self):
        return self.isStarted() and not self.isFinished()

    def isPending(self):
        return not self.isStarted()

    def isAvailable(self):
        return not self.isFinished()

    def startFromNow(self):
        now = datetime.now(pytz.utc)
        delta = self.open_datetime - now
        return fmtHrsMins(delta.total_seconds())

    def endFromNow(self):
        now = datetime.now(pytz.utc)
        delta = self.close_datetime - now
        return fmtHrsMins(delta.total_seconds())

    def endFromNowFullMin(self):
        now = datetime.now(pytz.utc)
        delta = self.close_datetime - now
        return fmtDaysHrsMinsShort(delta.total_seconds())

    def toGuerrillaStr(self):
        return fmtTimeShort(self.startPst())

    def toDateStr(self):
        return self.server + "," + self.group + "," + fmtTime(self.startPst()) + "," + fmtTime(self.startEst()) + "," + self.startFromNow()

    def toPartialEvent(self, pe):
        if self.isStarted():
            return self.group + " " + self.endFromNow() + "   " + self.nameAndModifier()
        else:
            return self.group + " " + fmtTimeShort(self.startPst()) + " " + fmtTimeShort(self.startEst()) + " " + self.startFromNow() + " " + self.nameAndModifier()


class PgEventType(PgItem):
    @staticmethod
    def file_name():
        return 'attributeList.jsp'

    def __init__(self, item):
        self.seq = item['EVENT_SEQ']
        self.name = item['EVENT_NAME_US']


def make_roma_subname(name_jp):
    subname = name_jp.replace('＝', '')
    adjusted_subname = ''
    for part in subname.split('・'):
        roma_part = romkan.to_roma(part)
        # TODO: never finished this up
        roma_part_undiecode = unidecode.unidecode(part)

        if part != roma_part and not rpadutils.containsJp(roma_part):
            adjusted_subname += ' ' + roma_part.strip('-')
    return adjusted_subname.strip()


def int_or_none(maybe_int: str):
    return int(maybe_int) if len(maybe_int) else None
