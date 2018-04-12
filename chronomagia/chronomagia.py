from _collections import OrderedDict
import asyncio
import csv
import difflib
import json
import os
from time import time
import traceback

import aiohttp
import discord
from discord.ext import commands

from __main__ import send_cmd_help, set_cog
from cogs.utils import checks
from cogs.utils.chat_formatting import pagify, box
from cogs.utils.dataIO import dataIO

from . import rpadutils
from .rpadutils import CogSettings
from .rpadutils import Menu, char_to_emoji
from .utils.chat_formatting import *


SUMMARY_SHEET = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vQI-NBN3IUemNXq4rJ-pHce_Y5HXpnJnYwmujpIO0ClC3vXhs6YmwqYzEacFlknWQ7BEojhDJac-sY-/pub?gid=907773684&single=true&output=csv'
EFFECTS_SHEET = ''


class ChronoMagia:
    """ChronoMagia."""

    def __init__(self, bot):
        self.bot = bot
        self.settings = ChronoMagiaSettings("chronomagia")
        self.card_data = []

    async def reload_cm_task(self):
        await self.bot.wait_until_ready()
        while self == self.bot.get_cog('ChronoMagia'):
            try:
                await self.refresh_data()
                print('Done refreshing ChronoMagia')
            except Exception as ex:
                print("reload CM loop caught exception " + str(ex))
                traceback.print_exc()
            await asyncio.sleep(60 * 60 * 1)

    async def refresh_data(self):
        await self.bot.wait_until_ready()

        standard_expiry_secs = 2 * 60 * 60
        summary_text = await rpadutils.makeAsyncCachedPlainRequest(
            'data/chronomagia/summary.csv', SUMMARY_SHEET, standard_expiry_secs)
        file_reader = csv.reader(summary_text.splitlines(), delimiter=',')
        next(file_reader, None)  # skip header
        self.card_data.clear()
        for row in file_reader:
            if not row or not row[0].strip():
                # Ignore empty rows
                continue
            self.card_data.append(CmCard(row))

    @commands.command(pass_context=True)
    async def cmid(self, ctx, *, query: str):
        """ChronoMagia query."""
        query = clean_name_for_query(query)
        if len(query) < 3:
            await self.bot.say(inline('query must be at least 3 characters'))
            return

        c = None
        names_to_card = {x.name_clean: x for x in self.card_data}
        matches = list(filter(lambda x: x.startswith(query), names_to_card.keys()))
        if not matches:
            matches = difflib.get_close_matches(query, names_to_card.keys(), n=1, cutoff=.6)

        if not matches:
            await self.bot.say(inline('no matches'))
            return

        c = names_to_card[matches[0]]
        msg = '{} : {} {}'.format(c.name, c.rarity, c.monspell)
        type_text = ''
        if c.monspell == 'Spell':
            pass
        elif c.type2:
            type_text = '{}/{} '.format(c.type1, c.type2)
        else:
            type_text = '{} '.format(c.type1)
        msg += '\n{}Cost:{} Atk:{} Def:{}'.format(type_text, c.cost, c.atk, c.defn)
        if c.atkeff:
            msg += ' AtkEff:{}'.format(c.atkeff)
        cardeff = c.cardeff or 'No effect'
        msg += '\nEffect: {}'.format(cardeff)
        await self.bot.say(box(msg))


def clean_name_for_query(name: str):
    return name.strip().lower().replace(',', '')


class ChronoMagiaSettings(CogSettings):
    def make_default_settings(self):
        config = {}
        return config


class CmCard(object):
    def __init__(self, csv_row):
        row = [x.strip() for x in csv_row]
        self.name = row[0]
        self.name_clean = clean_name_for_query(self.name)
        self.rarity = row[1]
        self.monspell = row[2]
        self.cost = row[3]
        self.type1 = row[4]
        self.type2 = row[5]
        self.atk = row[6]
        self.defn = row[7]
        self.atkeff = row[8]
        self.cardeff = row[9]


def setup(bot):
    n = ChronoMagia(bot)
    bot.add_cog(n)
    bot.loop.create_task(n.reload_cm_task())
