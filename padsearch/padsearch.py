import json
import math

import discord
from discord.ext import commands
from ply import lex, yacc
from png import itertools

from __main__ import user_allowed, send_cmd_help

from .utils import checks
from .utils.chat_formatting import box, inline

HELP_MSG = """
^search <specification string>

Colors can be any of:
  fire water wood light dark
  heart jammer poison mortal

Options which take multiple colors should be comma-separated.

Single instance filters
* cd(n)       : Min cd <= n
* haste(n)    : Skill cds reduced by n
* shuffle     : Board shuffle (aka refresh)
* unlock      : Orb unlock

Multiple instance filters 
* active(str)     : Active skill name/description
* board(colors,)  : Board change to a comma-sep list of colors
* column(color)   : Creates a column of a color
* leader(str)     : Leader skill description
* name(str)       : Monster name 
* row(color)      : Creates a row of a color
* type(str)       : Monster type

Coming soon: 
* convert(c1, c2) : Convert from color 1 to color 2
"""


TYPES = [
    "attacker",
    "awoken",
    "balance",
    "devil",
    "enhance",
    "evolve",
    "god",
    "healer",
    "machine",
    "physical",
    "protected",
    "vendor",
]

ORB_TYPES = [
    'any',
    'fire',
    'water',
    'wood',
    'light',
    'dark',
    'heal',
    'jammer',
    'poison',
    'mortal',
]


def assert_color(value):
    if value not in ORB_TYPES:
        raise Exception('Unexpected orb {}, expected one of {}'.format(value, ORB_TYPES))
    return value


def assert_colors(values):
    for value in values:
        assert_color(value)
    return values


def split_csv_colors(value):
    parts = [p.strip() for p in value.split(',')]
    return assert_colors(parts)


def replace_colors(text: str):
    text = text.replace('red', 'fire')
    text = text.replace('blue', 'water')
    text = text.replace('green', 'wood')
    text = text.replace('heart', 'heal')
    return text


def clean_name(txt, name):
    return txt.replace(name, '').strip('() ')


def board_filter(colors):
    def fn(m, colors=colors):
        # Copy for safety
        colors = list(colors)
        m_colors = list(m.search.board_change)

        if len(m_colors) != len(colors):
            return False

        any_values = 0
        for c in colors:
            if c == 'any':
                any_values += 1
            else:
                if c in m_colors:
                    m_colors.remove(c)
                else:
                    return False

        # Check remaining anys
        return any_values == len(m_colors)

    return fn


class PadSearchLexer(object):
    tokens = [
        'ACTIVE',
        'BOARD',
        'CD',
        'COLUMN',
        'HASTE',
        'LEADER',
        'NAME',
        'ROW',
        'TYPE',
        'SHUFFLE',
        'UNLOCK',
    ]

    def t_ACTIVE(self, t):
        r'active\(.+?\)'
        t.value = clean_name(t.value, 'active')
        t.value = replace_colors(t.value)
        return t

    def t_BOARD(self, t):
        r'board\([a-zA-z, ]+\)'
        t.value = clean_name(t.value, 'board')
        t.value = replace_colors(t.value)
        return t

    def t_CD(self, t):
        r'cd\(\d\)'
        t.value = clean_name(t.value, 'cd')
        t.value = int(t.value)
        return t

    def t_COLUMN(self, t):
        r'column\([a-zA-z]+\)'
        t.value = clean_name(t.value, 'column')
        t.value = replace_colors(t.value)
        return t

    def t_HASTE(self, t):
        r'haste\(\d\)'
        t.value = clean_name(t.value, 'haste')
        t.value = int(t.value)
        return t

    def t_LEADER(self, t):
        r'leader\(.+?\)'
        t.value = clean_name(t.value, 'leader')
        t.value = replace_colors(t.value)
        return t

    def t_NAME(self, t):
        r'name\([a-zA-Z0-9 ]+\)'
        t.value = clean_name(t.value, 'name')
        return t

    def t_ROW(self, t):
        r'row\([a-zA-Z]+\)'
        t.value = clean_name(t.value, 'row')
        t.value = replace_colors(t.value)
        return t

    def t_SHUFFLE(self, t):
        r'shuffle(\(\))?'
        return t

    def t_TYPE(self, t):
        r'type\([a-zA-z]+\)'
        t.value = clean_name(t.value, 'type')
        return t

    def t_UNLOCK(self, t):
        r'unlock(\(\))?'
        return t

    t_ignore = ' \t\n'

    def t_error(self, t):
        raise TypeError("Unknown text '%s'" % (t.value,))

    def build(self, **kwargs):
        # pass debug=1 to enable verbose output
        self.lexer = lex.lex(module=self)
        return self.lexer


class SearchConfig(object):

    def __init__(self, lexer):
        self.cd = None
        self.haste = None
        self.shuffle = None
        self.unlock = None

        self.active = []
        self.board = []
        self.column = []
        self.leader = []
        self.name = []
        self.row = []
        self.types = []

        for tok in iter(lexer.token, None):
            type = tok.type
            value = tok.value
            self.cd = self.setIfType('CD', type, self.cd, value)
            self.haste = self.setIfType('HASTE', type, self.haste, value)
            self.shuffle = self.setIfType('SHUFFLE', type, self.shuffle, value)
            self.unlock = self.setIfType('UNLOCK', type, self.unlock, value)

            if type == 'ACTIVE':
                self.active.append(value)
            if type == 'BOARD':
                self.board.append(split_csv_colors(value))
            if type == 'COLUMN':
                self.column.append(assert_colors(value))
            if type == 'LEADER':
                self.leader.append(value)
            if type == 'NAME':
                self.name.append(value)
            if type == 'ROW':
                self.row.append(assert_colors(value))
            if type == 'TYPE':
                if value not in TYPES:
                    raise Exception('Unexpected type {}, expected one of {}'.format(value, TYPES))
                self.types.append(value)

        self.filters = list()

        # Single
        if self.cd:
            self.filters.append(lambda m: m.search.active_min and m.search.active_min <= self.cd)

        if self.haste:
            text = 'charge by {}'.format(self.haste)
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        if self.shuffle:
            text = 'switch orbs'
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        if self.unlock:
            text = 'removes lock'
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        # Multiple
        if self.active:
            filters = []
            for ft in self.active:
                text = ft.lower()
                filters.append(lambda m, t=text: t in m.search.active)
            self.filters.append(self.or_filters(filters))

        if self.board:
            filters = []
            for colors in self.board:
                filters.append(board_filter(colors))
            self.filters.append(self.or_filters(filters))

        if self.column:
            filters = []
            for ft in self.column:
                text = ft.lower()
                if text == 'any':
                    filters.append(lambda m: m.search.column_convert)
                else:
                    filters.append(lambda m, t=text: t in m.search.column_convert)
            self.filters.append(self.or_filters(filters))

        if self.leader:
            filters = []
            for ft in self.leader:
                text = ft.lower()
                filters.append(lambda m, t=text: t in m.search.leader)
            self.filters.append(self.or_filters(filters))

        if self.name:
            filters = []
            for ft in self.name:
                text = ft.lower()
                filters.append(lambda m, t=text: t in m.search.name)
            self.filters.append(self.or_filters(filters))

        if self.row:
            filters = []
            for ft in self.row:
                text = ft.lower()
                if text == 'any':
                    filters.append(lambda m: m.search.row_convert)
                else:
                    filters.append(lambda m, t=text: t in m.search.row_convert)
            self.filters.append(self.or_filters(filters))

        if self.types:
            filters = []
            for ft in self.types:
                text = ft.lower()
                filters.append(lambda m, t=text: t in m.search.types)
            self.filters.append(self.or_filters(filters))

        if not self.filters:
            raise Exception('You need to specify at least one filter')

    def check_filters(self, m):
        for f in self.filters:
            if not f(m):
                return False
        return True

    def or_filters(self, filters):
        def fn(m, filters=filters):
            for f in filters:
                if f(m):
                    return True
            return False
        return fn

    def setIfType(self, expected_type, given_type, current_value, new_value):
        if expected_type != given_type:
            return current_value
        if current_value is not None:
            raise Exception('You set {} more than once'.format(given_type))
        return new_value


class PadSearch:
    """PAD data searching."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True)
    async def helpsearch(self, ctx):
        """Help info for the search command."""
        await self.bot.whisper(box(HELP_MSG))

    @commands.command(pass_context=True)
    async def search(self, ctx, *, filter_spec: str):
        """Searches for monsters based on a filter you specify.

        Use ^helpsearch for more info.
        """

        lexer = PadSearchLexer().build()
        lexer.input(filter_spec)

        try:
            config = SearchConfig(lexer)
        except Exception as ex:
            await self.bot.say(inline(str(ex)))
            return

        pg_cog = self.bot.get_cog('PadGuide2')
        monsters = pg_cog.database.all_monsters()
        matched_monsters = list(filter(config.check_filters, monsters))
        matched_monsters.sort(key=lambda m: m.monster_no_na, reverse=True)

        msg = 'Matched {} monsters'.format(len(matched_monsters))
        if len(matched_monsters) > 10:
            msg += ' (limited to 10)'
            matched_monsters = matched_monsters[0:10]

        for m in matched_monsters:
            msg += '\n\tNo. {} {}'.format(m.monster_no_na, m.name_na)

        await self.bot.say(box(msg))

    @commands.command(pass_context=True)
    @checks.is_owner()
    async def debugsearch(self, ctx, *, query):
        padinfo_cog = self.bot.get_cog('PadInfo')
        m, err, debug_info = padinfo_cog.findMonster(query)

        if m is None:
            await self.bot.say(box('No match: ' + err))
            return

        await self.bot.say(box(json.dumps(m.search, indent=2, default=lambda o: o.__dict__)))


def setup(bot):
    n = PadSearch(bot)
    bot.add_cog(n)
