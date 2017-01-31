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

# monsterInfoList.jsp
#         {
#             "FODDER_EXP": "675.0",
#             "HISTORY_JP": "[2016-12-16] \u65b0\u898f\u8ffd\u52a0",
#             "HISTORY_KR": "[2016-12-16] \uc2e0\uaddc\ucd94\uac00",
#             "HISTORY_US": "[2016-12-16] New Added",
#             "MONSTER_NO": "3382",
#             "ON_KR": "1",
#             "ON_US": "1",
#             "PAL_EGG": "0",
#             "RARE_EGG": "0",
#             "SELL_PRICE": "300.0",
#             "TSR_SEQ": "86",
#             "TSTAMP": "1481846935838"
#         },
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
    return name

class PgDungeon:
    def __init__(self, item):
        self.seq = item['DUNGEON_SEQ']
        self.type = DungeonType(int(item['DUNGEON_TYPE']))
        self.name = item['NAME_US']
        self.tdt = item['TDT_SEQ']

class PgEventList:
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

class PgEvent:
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
        close_time_strstr = item['CLOSE_DATE'] + " " + item['CLOSE_HOUR'] + ":" + item['CLOSE_MINUTE']

        self.open_datetime = datetime.strptime(open_time_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        self.close_datetime = datetime.strptime(close_time_strstr, "%Y-%m-%d %H:%M").replace(tzinfo=tz)

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
         return output;

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

class PgEventType:
    def __init__(self, item):
        self.seq = item['EVENT_SEQ']
        self.name = item['EVENT_NAME_US']


# skillRotationList.jsp
#         {
#             "MONSTER_NO": "915",
#             "SERVER": "JP",
#             "STATUS": "0",
#             "TSR_SEQ": "2",
#             "TSTAMP": "1481627094573"
#         }
# TSR_SEQ is the primary key
# Status is always 0
class PgSkillRotation:
    def __init__(self, item):
        self.tsr_seq = item['TSR_SEQ']
        self.monster_id = item['MONSTER_NO']
        self.server = item['SERVER']

# skillRotationListList.jsp
#         {
#             "ROTATION_DATE": "2016-12-14",
#             "STATUS": "0",
#             "TSRL_SEQ": "960",
#             "TSR_SEQ": "86",
#             "TSTAMP": "1481627993157",
#             "TS_SEQ": "9926"
#         }
# TSRL_SEQ is the primary key
# TS_SEQ is the current skill
# TSR_SEQ links to skillRotationList, get the monster_no out of there
class PgDatedSkillRotation:
    def __init__(self, item):
        self.tsrl_seq = item['TSRL_SEQ']
        self.tsr_seq = item['TSR_SEQ']
        self.active_id = item['TS_SEQ']
        self.rotation_date_str = item['ROTATION_DATE']

        self.rotation_date = None
        if len(self.rotation_date_str):
             self.rotation_date = datetime.strptime(self.rotation_date_str, "%Y-%m-%d").date()

class PgMergedRotation:
    def __init__(self, rotation, dated_rotation):
        self.monster_id = rotation.monster_id
        self.server = rotation.server
        self.rotation_date = dated_rotation.rotation_date
        self.active_id = dated_rotation.active_id

        self.resolved_monster = None  # The monster that does the skillup
        self.resolved_active = None  # The skill for this server
