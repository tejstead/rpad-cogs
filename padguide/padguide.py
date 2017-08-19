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
# dungeonList.jsp


class PgDungeon:
    def __init__(self, item):
        self.seq = item['DUNGEON_SEQ']
        self.type = DungeonType(int(item['DUNGEON_TYPE']))
        self.name = item['NAME_US']
        self.tdt = item['TDT_SEQ']

# {
#     "MONSTER_NO": "3427",
#     "ORDER_IDX": "20",
#     "STATUS": "0",
#     "TDMD_SEQ": "967",
#     "TDM_SEQ": "17816",
#     "TSTAMP": "1489371218890"
# },
# dungeonMonsterDropList.jsp
# Seems to be dedicated skillups only, like collab drops


class PgDungeonMonsterDrop:
    def __init__(self, item):
        self.monster_id = item['MONSTER_NO']
        self.status = item['STATUS']  # if 1, good, if 0, bad
        self.tdmd_seq = item['TDMD_SEQ']  # unique id
        self.tdm_seq = item['TDM_SEQ']  # PgDungeonMonster id


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
# dungeonMonsterList.jsp
class PgDungeonMonster:
    def __init__(self, item):
        self.tdm_seq = item['TDM_SEQ']  # unique id
        self.drop_monster_id = item['DROP_NO']  # PgMonster unique id
        self.monster_id = item['MONSTER_NO']  # PgMonster unique id
        self.dungeon_seq = item['DUNGEON_SEQ']  # PgDungeon uniqueId
        self.tsd_seq = item['TSD_SEQ']  # ??


class PgMonsterDropInfoCombined:
    def __init__(self, monster_id, dungeon_monster_drop, dungeon_monster, dungeon):
        self.monster_id = monster_id
        self.dungeon_monster_drop = dungeon_monster_drop
        self.dungeon_monster = dungeon_monster
        self.dungeon = dungeon


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


class PgEventType:
    def __init__(self, item):
        self.seq = item['EVENT_SEQ']
        self.name = item['EVENT_NAME_US']
