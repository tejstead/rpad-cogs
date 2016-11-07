import http.client
import urllib.parse
import json
import re
import csv
import random

import os

import time
from datetime import datetime
from datetime import timedelta
from dateutil import tz
import pytz
import traceback


import time
import threading
import asyncio
import discord

from enum import Enum

from discord.ext import commands
from .utils.chat_formatting import *
from .utils.dataIO import fileIO
from .utils import checks
from .utils.twitter_stream import *
from __main__ import user_allowed, send_cmd_help

from itertools import groupby
from collections import defaultdict
from operator import itemgetter
# from copy import deepcopy

from .utils.padguide import *
from .utils.cog_settings import *

import prettytable
from setuptools.command.alias import alias
from builtins import filter

from .padinfo import EXPOSED_PAD_INFO
from _collections import OrderedDict

def normalizeServer(server):
    server = server.upper()
    return 'NA' if server == 'US' else server

SUPPORTED_SERVERS = ["NA", "JP"]


class PadRem:
    def __init__(self, bot):
        self.bot = bot
        
        self.settings = PadRemSettings("padrem")
        
        self.pgrem = PgRemWrapper()
        
        if EXPOSED_PAD_INFO is not None:
            self.pgrem.populateWithMonsters(EXPOSED_PAD_INFO.pginfo.full_monster_map, self.settings.getBoosts())    

        
    async def on_ready(self):
        """ready"""
        print("started padrem")
        self.pgrem.populateWithMonsters(EXPOSED_PAD_INFO.pginfo.full_monster_map, self.settings.getBoosts())

    @commands.command(name="setboost", pass_context=True)
    @checks.mod_or_permissions(manage_server=True)
    async def _setboost(self, ctx, machine_id : str, boost_rate : int):
        """Sets the boost rate for a specific REM.
        
        machine_id should be the value in () in the rem list, e.g for
          gf -> Godfest x4 (711) REM (JP) with Aqua Carnival x3 (561)
          
        Use 711 to set the godfest rate and 561 to set the carnival rate.
        
        The boost_rate should an integer >= 1.
        
        You will need to reload the module after changing this.
        """
        self.settings.setBoost(machine_id, boost_rate)
        await self.bot.say(box('Done'))

    @commands.command(name="remlist", pass_context=True)
    async def _remlist(self, ctx):
        """Prints out all available rare egg machines that can be rolled."""
        msg = ""
        
        for server, config in self.pgrem.server_to_config.items():
            msg += "Current REM info for {}:\n".format(server)
            for key, machine in config.machines.items():
                msg += '\t{:7} -> {}\n'.format(key, machine.machine_name)
            msg += '\n'
            
        await self.bot.say(box(msg))

    @commands.command(name="reminfo", pass_context=True)
    async def _reminfo(self, ctx, server, rem_name):
        """Prints out detailed information on the contents of a REM.
        
        You must specify the server, NA or JP.
        You must specify the rem name. Use 'remlist' to get the full
        set of REMs that can be rolled.
        """
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, JP")
            return
        
        config = self.pgrem.server_to_config[server]
        
        if rem_name not in config.machines:
            await self.bot.say(box('Unknown machine name'))
            return
        
        machine = config.machines[rem_name]
        
        await self.sayPageOutput(machine.toDescription())

    @commands.command(name="rollrem", pass_context=True)
    async def _rollrem(self, ctx, server, rem_name):
        """Rolls a rare egg machine and prints the result. 

        You must specify the server, NA or JP.
        You must specify the rem name. Use 'remlist' to get the full
        set of REMs that can be rolled.
        """
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, JP")
            return
        
        config = self.pgrem.server_to_config[server]
        
        if rem_name not in config.machines:
            await self.bot.say(box('Unknown machine name'))
            return
        
        machine = config.machines[rem_name]
        monster = machine.pickMonster()
        
        msg = 'You rolled : #{} {}'.format(monster.monster_id_jp, monster.name_na)
        await self.bot.say(box(msg))

    @commands.command(name="rollremfor", pass_context=True)
    async def _rollremfor(self, ctx, server : str, rem_name : str, monster_query : str):
        """Rolls a rare egg machine until the selected monster pops out. 

        You must specify the server, NA or JP.
        You must specify the rem name. Use 'remlist' to get the full
        set of REMs that can be rolled.
        You must specify a monster id present within the egg machine.
        """
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, JP")
            return
        
        config = self.pgrem.server_to_config[server]
        
        if rem_name not in config.machines:
            await self.bot.say(box('Unknown machine name'))
            return
        
        machine = config.machines[rem_name]
        
        check_monster_fn = lambda m: monster_query.lower() in m.name_na.lower() or monster_query.lower() in m.name_jp.lower()
        if monster_query.isdigit():
            check_monster_fn = lambda m: int(monster_query) == m.monster_id_jp
        
        found = False
        for m in machine.monster_id_jp_to_monster.values():
            if check_monster_fn(m):
                found = True
                break

        if not found:
            await self.bot.say(box('That monster is not available in this REM'))
            return
        
        picks = 0
        roll_stones = machine.stones_per_roll
        stone_price = 3.53/5 if server == 'NA' else 2.65/5
        while picks < 500:
            monster = machine.pickMonster()
            picks += 1
            if check_monster_fn(monster):
                stones = picks * roll_stones
                price = stones * stone_price
                msg = 'It took {} tries, ${:.0f}, and {} stones to pull : #{} {}'.format(picks, price, stones, monster.monster_id_jp, monster.name_na)
                await self.bot.say(box(msg))
                return

        await self.bot.say(box('You failed to roll your monster in 500 tries'))
        
    async def sayPageOutput(self, msg, format_type=box):
        msg = msg.strip()
        msg = pagify(msg, ["\n"], shorten_by=20)
        for page in msg:
            try:
                await self.bot.say(format_type(page))
            except Exception as e:
                print("page output failed " + str(e))
                print("tried to print: " + page)
        
    async def whisperPageOutput(self, msg, format_type=box):
        msg = msg.strip()
        msg = pagify(msg, ["\n"], shorten_by=20)
        for page in msg:
            try:
                await self.bot.whisper(format_type(page))
            except Exception as e:
                print("page output failed " + str(e))
                print("tried to print: " + page)


def setup(bot):
    print('padrem bot setup')
    n = PadRem(bot)
    bot.add_cog(n)
    print('done adding padrem bot')


class PadRemSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'machine_id_to_boost': {}
        }
        return config
    
    def getBoosts(self):
        return self.bot_settings['machine_id_to_boost']
    
    def setBoost(self, machine_id, boost):
        self.getBoosts()[machine_id] = int(boost)
        self.save_settings()
        
def loadJsonToItem(filename, itemtype):
    json_data = fileIO('data/padevents/' + filename, 'load')
    results = list()
    for item in json_data['items']:
        results.append(itemtype(item))
    return results
        

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
        self.delete = item['DEL_YN'] # Y, N
        self.show = item['SHOW_YN'] # Y, N
        self.rem_type = RemType(item['TEC_SEQ']) # matches RemType
        self.egg_id = item['TET_SEQ'] # primary key
        self.row_type = RemRowType(item['TYPE']) # 0-> row with just name, 1-> row with date
        
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
        self.language = item['LANGUAGE'] # US, JP, KR
        self.delete = item['DEL_YN'] # Y, N
        self.primary_id = item['TETN_SEQ'] # primary key
        self.egg_id = item['TET_SEQ'] # fk to PgEggInstance

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
        self.primary_id = item['TEM_SEQ'] # primary key
        self.egg_id = item['TET_SEQ'] # fk to PgEggInstance

class PgEggMachine:
    def __init__(self, egg_instance, egg_name, egg_monster_list):
        self.egg_instance = egg_instance        
        self.egg_name = egg_name
        self.egg_monster_list = egg_monster_list

# rem simulator

class PgRemWrapper:
    def __init__(self):
        egg_instance_list = loadJsonToItem('eggTitleList.jsp', PgEggInstance)
        egg_name_list = loadJsonToItem('eggTitleNameList.jsp', PgEggName)
        egg_monster_list = loadJsonToItem('eggMonsterList.jsp', PgEggMonster)
        
        # Make sure machine is live
        egg_instance_list = list(filter(lambda x: x.show == 'Y' and x.delete == 'N', egg_instance_list))
        
        # Make sure machine is not PAL
        egg_instance_list = list(filter(lambda x: x.rem_type in (RemType.godfest, RemType.rare), egg_instance_list))
        
        # Get rid of Korea, no one plays there
        egg_instance_list = list(filter(lambda x: x.server != 'KR', egg_instance_list))
        
        # Make sure name is live, and English
        egg_name_list = list(filter(lambda x: x.language == 'US' and x.delete == 'N', egg_name_list))
        
        # Get rid of deleted/bad eggs
        egg_monster_list = list(filter(lambda x: x.delete == 'N' and x.monster_id != '0', egg_monster_list))
        
        egg_id_to_egg_name = {egg_name.egg_id: egg_name for egg_name in egg_name_list}
        egg_id_to_egg_monster = defaultdict(list)
        
        for egg_monster in egg_monster_list:
            egg_id_to_egg_monster[egg_monster.egg_id].append(egg_monster) 
        
        egg_machines = list()
        for egg_instance in egg_instance_list:
            egg_name = egg_id_to_egg_name.get(egg_instance.egg_id)
            if egg_name is None:
                egg_name = makeBlankEggName(egg_instance.egg_id)
            monster_list = egg_id_to_egg_monster[egg_instance.egg_id]
            egg_machines.append(PgEggMachine(egg_instance, egg_name, monster_list))
            
        self.egg_machines = list(sorted(egg_machines, key=lambda x: (x.egg_instance.server, x.egg_instance.rem_type.value, x.egg_instance.order)))
            
    def populateWithMonsters(self, monster_map, id_to_boost_map):
        gfe_rem_list = list()
        for m in monster_map.values():
            if m.is_gfe and len(m.evo_from) == 0:
                gfe_rem_list.append(m)
                
        self.gfe_rem_list = gfe_rem_list
        
        global_rem_list = list()
        
        current_list = None
        modifier_list = list()
         
        for em in self.egg_machines:
            converted_monsters = list()
            for m in em.egg_monster_list:
                rm = monster_map.get(m.monster_id)
                if rm is not None:
                    converted_monsters.append(rm)
                else:
                    print('\t failed to look up {}'.format(m.monster_id))
         
            egg_instance = em.egg_instance
            egg_name = em.egg_name
            boost_rate = id_to_boost_map.get(egg_instance.egg_id)
            
            if egg_instance.server == '':
                for m in converted_monsters:
                    if m.monster_id_jp not in PADGUIDE_EXCLUSIVE_MISTAKES:
                        global_rem_list.append(m)
            else:
                if egg_instance.row_type == RemRowType.divider:
                    current_list = list()
                    modifier_list.append(EggMachineModifier(egg_instance, egg_name, current_list, boost_rate))
                    
                current_list.extend(converted_monsters)
        
        self.global_rem_list = global_rem_list
        self.modifier_list = modifier_list
        
        self.server_to_config = {}
        for server in ['NA', 'JP']:
            mods = [emm for emm in modifier_list if emm.server == server]
            self.server_to_config[server] = PgServerRemConfig(server, global_rem_list, gfe_rem_list, mods)
                        

class EggMachine:
    def __init__(self):
        self.machine_id = None
        self.machine_name = None
        
        self.monster_id_to_boost = {}
        self.monster_id_to_monster = {}
        self.monster_id_jp_to_monster = {}
        self.monster_entries = list()
        self.stone_count = 5
        
    def addMonsterAndBoost(self, monster, boost):
        saved_boost = self.monster_id_to_boost.get(monster.monster_id, boost)
        self.monster_id_to_boost[monster.monster_id] = max(boost, saved_boost)    
        self.monster_id_to_monster[monster.monster_id] = monster    
        self.monster_id_jp_to_monster[monster.monster_id_jp] = monster    
    
    def addMonster(self, monster, rate):
        for i in range(0, rate):
            self.monster_entries.append(monster)
            
    def pickMonster(self):
        if not len(self.monster_entries):
            return None
        return self.monster_entries[random.randrange(len(self.monster_entries))]
    
    def computeMonsterEntries(self):
        self.monster_entries.clear()
        for monster_id in self.monster_id_to_boost.keys():
            m = self.monster_id_to_monster[monster_id]
            self.addMonster(m, self.pointsForMonster(m))
    
    def pointsForMonster(self, monster):
        return (9 - monster.rarity) * self.monster_id_to_boost[monster.monster_id]

    def pointsForMonster(self, monster):
        id_monster_rates = self.rem_config['monster_id']
        if monster.monster_id_jp in id_monster_rates:
            return id_monster_rates[monster.monster_id_jp]
        else:
            return self.rem_config['rarity'][monster.rarity]
    
    def chanceOfMonster(self, monster):
        return self.pointsForMonster(monster) / len(self.monster_entries)
    
    def toDescription(self):
        return 'Egg machine (unknown)'
    
    def toLongDescription(self, include_monsters, rarity_cutoff, chance_cutoff=.005):
        msg = self.machine_name + '\n'
        
        cur_rarity = None
        cur_count = None
        cum_chance = None
        cur_msg = None
        
        for m in sorted(self.monster_id_to_monster.values(), key=lambda m: (m.rarity, m.monster_id_jp), reverse=True):
            if cur_rarity != m.rarity:
                if cur_rarity is not None:
                    msg += '{}* ({} monsters at {:.1%})\n'.format(cur_rarity, cur_count, cum_chance)
                    msg += cur_msg
                
                cur_rarity = m.rarity
                cur_count = 0
                cum_chance = 0.0
                cur_msg = ''
                
            chance = self.chanceOfMonster(m)
            cur_count += 1
            cum_chance += chance
            
            if include_monsters and cur_rarity >= rarity_cutoff and (chance >= chance_cutoff or cur_rarity > 6):
                cur_msg += '\t{: 5.1%} #{:4d} {}\n'.format(chance, m.monster_id_jp, m.name_na)
            
        msg += '{}* ({} monsters at {:.1%})\n'.format(cur_rarity, cur_count, cum_chance)
        msg += cur_msg
        return msg

class RareEggMachine(EggMachine):
    def __init__(self, server, global_rem_list, carnival_modifier):
        super(RareEggMachine, self).__init__()

        self.machine_name = 'REM ({})'.format(server)
        self.rem_config = DEFAULT_MACHINE_CONFIG
        self.stones_per_roll = self.rem_config['stones_per_roll']
        
        if carnival_modifier:
            self.machine_name += ' with {} x{} ({})'.format(carnival_modifier.name, carnival_modifier.boost_rate, carnival_modifier.egg_id)     
        
        for m in global_rem_list:
            if server == 'NA' and not m.on_us:
                continue
            self.addMonsterAndBoost(m, 1)
            
        if carnival_modifier is not None:
            for m in carnival_modifier.monster_list:
                if m.monster_id_jp in PADGUIDE_EXCLUSIVE_MISTAKES:
                    self.addMonsterAndBoost(m, 1)
                else:
                    self.addMonsterAndBoost(m, carnival_modifier.boost_rate)
        
        self.computeMonsterEntries()

    def toDescription(self):
        return self.toLongDescription(False, 0)

class GfEggMachine(RareEggMachine):
    def __init__(self, server, global_rem_list, gfe_rem_list, carnival_modifier, godfest_modifier):
        super(GfEggMachine, self).__init__(server, global_rem_list, carnival_modifier)

        self.machine_name = '{} Godfest x{} ({}) {}'.format(godfest_modifier.open_date_str, godfest_modifier.boost_rate, godfest_modifier.egg_id, self.machine_name)
        
        for m in gfe_rem_list:
            self.addMonsterAndBoost(m, 1)
        
        for m in godfest_modifier.monster_list:
            self.addMonsterAndBoost(m, godfest_modifier.boost_rate)
            
        self.computeMonsterEntries()

    def toDescription(self):
        return self.toLongDescription(True, 6)

class CollabEggMachine(EggMachine):
    def __init__(self, collab_modifier):
        super(CollabEggMachine, self).__init__()
        
        self.machine_id = int(collab_modifier.egg_id)
        self.machine_name = '{} ({})'.format(collab_modifier.name, collab_modifier.egg_id)
        
        self.rem_config = DEFAULT_COLLAB_CONFIG
        if self.machine_id == 905:
            self.rem_config = IMOUTO_COLLAB_CONFIG
        
        self.stones_per_roll = self.rem_config['stones_per_roll']
        
        for m in collab_modifier.monster_list:
            self.addMonsterAndBoost(m, 1)
            
        self.computeMonsterEntries()

    def toDescription(self):
        return self.toLongDescription(True, 1)
            

DEFAULT_MACHINE_CONFIG = {
    'stones_per_roll': 5,
    'monster_id': {},
    'rarity': {
        8: 3,
        7: 3,
        6: 6,
        5: 12,
        4: 24,
    },
}

DEFAULT_COLLAB_CONFIG = {
    'stones_per_roll': 5,
    'monster_id': {},
    'rarity': {
        8: 1,
        7: 3,
        6: 4,
        5: 9,
        4: 12,
    },
}

# TODO: make this configurable
IMOUTO_COLLAB_CONFIG = {
    'stones_per_roll': 10,
    'monster_id': {},
    'rarity': {
        8: 0,
        7: 15,
        6: 51,
        5: 145,
    },
}

class EggMachineModifier:
    def __init__(self, egg_instance, egg_name, monster_list, boost_rate):
        self.server = egg_instance.server
        self.egg_id = egg_instance.egg_id
        self.order = egg_instance.order
        self.start_datetime = egg_instance.start_datetime
        self.end_datetime = egg_instance.end_datetime
        self.open_date_str = egg_instance.open_date_str
        
        
        self.rem_type = egg_instance.rem_type
        self.name = egg_name.name
            
        self.monster_list = monster_list
#         self.monster_to_boost = {}

        self.boost_rate = 1
        self.boost_is_default = True
        
        if boost_rate is not None:
            self.boost_rate = boost_rate
            self.boost_is_default = False
        elif self.isGodfest():
            self.boost_rate = 4
        elif self.isCarnival():
            self.boost_rate = 3
        
    def isGodfest(self):
        return self.rem_type == RemType.godfest
    
    def isRare(self):
        return self.rem_type == RemType.rare
    
    def isCarnival(self):
        name = self.name.lower()
        return self.isRare() and ('gala' in name or 'carnival' in name)
        
    def getName(self):
        if self.rem_type == RemType.godfest.value:
            return 'Godfest x{}'.format(self.boost_rate)
        else:
            return self.name
        

class PgServerRemConfig:
    def __init__(self, server, global_rem_list, gfe_rem_list, modifier_list):
        self.godfest_modifiers = list()
        self.collab_modifiers = list()
        self.carnival_modifier = None
        
        for modifier in modifier_list:
            if modifier.isGodfest():
                self.godfest_modifiers.append(modifier)
            elif modifier.isCarnival():
                self.carnival_modifier = modifier
            else:
                self.collab_modifiers.append(modifier)
                
        self.base_machine = RareEggMachine(server, global_rem_list, self.carnival_modifier)
        
        self.godfest_machines = list()
        for godfest_modifier in self.godfest_modifiers:
            self.godfest_machines.append(GfEggMachine(server, global_rem_list, gfe_rem_list, self.carnival_modifier, godfest_modifier))
        
        self.collab_machines = list()
        for collab_modifier in self.collab_modifiers:
            self.collab_machines.append(CollabEggMachine(collab_modifier))
            
        self.machines = OrderedDict()
        self.machines['rem'] = self.base_machine
        for idx, machine in enumerate(self.godfest_machines):
            suffix = '' if idx == 0 else str(idx+1)
            self.machines['gf' + suffix] = machine
        for idx, machine in enumerate(self.collab_machines):
            suffix = '' if idx == 0 else str(idx+1)
            self.machines['collab' + suffix] = machine
            
                

PADGUIDE_EXCLUSIVE_MISTAKES = [
  2665, # Red Gemstone, Silk
  2666, # Evo'd Silk
  2667, # Blue Gemstone, Carat
  2668, # Evo'd Carat
  2669, # Green Gemstone, Cameo
  2670, # Evo'd Cameo
  2671, # Light Gemstone, Facet
  2672, # Evo'd Facet
  2673, # Dark Gemstone, Sheen
  2674, # Evo'd Sheen
  
  2915, # Red Hero, Napoleon
  2916, # Evo'd Napoleon
  2917, # Blue Hero, Barbarossa
  2918, # Evo'd Barbarossa
  2919, # Green Hero, Robin Hood
  2920, # Evo'd Robin Hood
  2921, # Light Hero, Yang Guifei
  2922, # Evo'd Yang Guifei
  2923, # Dark Hero, Oda Nobunaga
  2924, # Evo'd Oda Nobunaga
]

# eggCategoryList.jsp
# lists the tec_sec order and visibility, not useful

# eggCategoryNameList
# using language=US
# TECN_SEQ is primary key?
# "TEC_SEQ": "1" -> 'Godfest', "TECN_SEQ": "5",
# "TEC_SEQ": "2" -> 'Rare Egg', "TECN_SEQ": "8",
# "TEC_SEQ": "3" -> 'Pal Egg'


