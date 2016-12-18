from datetime import datetime
from datetime import timedelta
from enum import Enum
import re

import discord
from discord.ext import commands
import pytz

from .rpadutils import *
from .utils.dataIO import fileIO


class PadGuide:
    def __init__(self, bot):
        self.bot = bot

def setup(bot):
    print('padguide setup')
    n = PadGuide(bot)
    bot.add_cog(n)


def loadJsonToItem(filename, itemtype):
    json_data = fileIO('data/padevents/' + filename, 'load')
    results = list()
    for item in json_data['items']:
        results.append(itemtype(item))
    return results

class PgAttribute:
    def __init__(self, item):
        self.name = item['TA_NAME_US']
        self.attribute_id = item['TA_SEQ']

class PgAwakening:
    def __init__(self, item):
        self.deleted = item['DEL_YN']
        self.monster_id = item['MONSTER_NO']
        self.order = int(item['ORDER_IDX'])
        self.tma_seq = item['TMA_SEQ']
        self.awakening_id = item['TS_SEQ']

class PgEvo:
    def __init__(self, item):
        self.monster_id = item['MONSTER_NO']
        self.to_monster_id = item['TO_NO']
        self.tv_seq = item['TV_SEQ']
        self.tv_type = item['TV_TYPE']

class PgMonsterAddInfo:
    def __init__(self, item):
        self.monster_id = item['MONSTER_NO']
        self.sub_type = item['SUB_TYPE']

class PgMonsterInfo:
    def __init__(self, item):
        self.monster_id = item['MONSTER_NO']
        self.on_us = item['ON_US']
        self.series_id = item['TSR_SEQ']

class PgBaseMonster:
    def __init__(self, item):
        self.monster_id = item['MONSTER_NO']
        self.monster_id_na = int(item['MONSTER_NO_US'])
        self.monster_id_jp = int(item['MONSTER_NO_JP'])

        self.hp = item['HP_MAX']
        self.atk = item['ATK_MAX']
        self.rcv = item['RCV_MAX']

        self.active_id = item['TS_SEQ_SKILL']
        self.leader_id = item['TS_SEQ_LEADER']

        self.rarity = item['RARITY']
        self.cost = item['COST']
        self.max_level = item['LEVEL']

        self.name_na = item['TM_NAME_US']
        self.name_jp = item['TM_NAME_JP']

        self.attr1 = item['TA_SEQ']
        self.attr2 = item['TA_SEQ_SUB']

        self.te_seq = item['TE_SEQ']

        self.type1 = item['TT_SEQ']
        self.type2 = item['TT_SEQ_SUB']

class PgSkill:
    def __init__(self, item):
        self.skill_id = item['TS_SEQ']
        self.name = item['TS_NAME_US']
        self.desc = item['TS_DESC_US']
        self.turn_min = item['TURN_MIN']
        self.turn_max = item['TURN_MAX']

class PgType:
    def __init__(self, item):
        self.type_id = item['TT_SEQ']
        self.name = item['TT_NAME_US']

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
class PgEggInstance:
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
            self.start_datetime = datetime.strptime(self.start_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            self.end_datetime = datetime.strptime(self.end_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)

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
class PgEggName:
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
class PgEggMonster:
    def __init__(self, item):
        self.delete = item['DEL_YN']
        self.monster_id = item['MONSTER_NO']
        self.primary_id = item['TEM_SEQ']  # primary key
        self.egg_id = item['TET_SEQ']  # fk to PgEggInstance

