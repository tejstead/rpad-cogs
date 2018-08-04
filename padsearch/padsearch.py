import json
import math

import discord
from discord.ext import commands
from ply import lex, yacc
from png import itertools

from __main__ import user_allowed, send_cmd_help

from . import rpadutils
from .utils import checks
from .utils.chat_formatting import box, inline

HELP_MSG = """
^search <specification string>

Colors can be any of:
  fire water wood light dark
Additionally, orb colors can be any of:
  heart jammer poison mortal and bomb

Options which take multiple colors should be comma-separated.

Single instance filters
* cd(n)       : Min cd <= n
* farmable    : Obtainable outside REM
* haste(n)    : Skill cds reduced by n
* inheritable : Can be inherited
* shuffle     : Board shuffle (aka refresh)
* unlock      : Orb unlock
* delay(n)    : Delay enemies by n
* attabsorb   : Attribute Absorb shield null
* absorbnull  : Damage Abasorb shield null
* combo(n)    : Increase combo count by n
* shield(n)   : Reduce damage taken by n%

Multiple instance filters 
* active(str)     : Active skill name/description
* board(colors,)  : Board change to a comma-sep list of colors
* color(color)    : Primary monster color
* column(color)   : Creates a column of a color
* hascolor(color) : Primary or secondary monster color
* leader(str)     : Leader skill description
* name(str)       : Monster name 
* row(color)      : Creates a row of a color
* type(str)       : Monster type
* convert(c1, c2) : Convert from color 1 to color 2, accepts any as entry as well
"""

COLORS = [
    'fire',
    'water',
    'wood',
    'light',
    'dark',
]

TYPES = [
    "attacker",
    "awoken",
    "balance",
    "devil",
    "dragon",
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
    value = replace_named_color(value)
    if value not in COLORS:
        raise rpadutils.ReportableError(
            'Unexpected color {}, expected one of {}'.format(value, COLORS))
    return value


def assert_orbcolor(value):
    value = replace_named_color(value)
    if value not in ORB_TYPES:
        raise rpadutils.ReportableError(
            'Unexpected orb {}, expected one of {}'.format(value, ORB_TYPES))
    return value


def assert_orbcolors(values):
    return [assert_orbcolor(c) for c in values]


def split_csv_orbcolors(value):
    parts = [p.strip() for p in value.split(',')]
    return assert_orbcolors(parts)


COLOR_REPLACEMENTS = {
    'red': 'fire',
    'r': 'fire',
    'blue': 'water',
    'b': 'water',
    'green': 'wood',
    'g': 'wood',
    'l': 'light',
    'd': 'dark',
    'heart': 'heal',
    'h': 'heal',
    'p': 'poison',
    'mortal': 'mortalpoison',
    'j': 'jammer',
    'o': 'bomb',
}


def replace_named_color(color: str):
    color = color.lower().strip()
    return COLOR_REPLACEMENTS.get(color, color)


def replace_colors_in_text(text: str):
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
        'COLOR',
        'COLUMN',
        'FARMABLE',
        'HASCOLOR',
        'HASTE',
        'INHERITABLE',
        'LEADER',
        'NAME',
        'ROW',
        'TYPE',
        'SHUFFLE',
        'UNLOCK',
        'DELAY',
        'REMOVE',
        'CONVERT',
        'COMBO',
        'ABSORBNULL',
        'ATTABSORB',
        'SHIELD',
    ]

    def t_ACTIVE(self, t):
        r'active\(.+?\)'
        t.value = clean_name(t.value, 'active')
        t.value = replace_colors_in_text(t.value)
        return t

    def t_BOARD(self, t):
        r'board\([a-zA-z, ]+\)'
        t.value = clean_name(t.value, 'board')
        t.value = replace_colors_in_text(t.value)
        return t

    def t_CD(self, t):
        r'cd\(\d+\)'
        t.value = clean_name(t.value, 'cd')
        t.value = int(t.value)
        return t

    def t_COLOR(self, t):
        r'color\([a-zA-z]+\)'
        t.value = clean_name(t.value, 'color')
        t.value = replace_colors_in_text(t.value)
        return t

    def t_COLUMN(self, t):
        r'column\([a-zA-z]+\)'
        t.value = clean_name(t.value, 'column')
        t.value = replace_colors_in_text(t.value)
        return t

    def t_FARMABLE(self, t):
        r'farmable(\(\))?'
        return t

    def t_HASCOLOR(self, t):
        r'hascolor\([a-zA-z]+\)'
        t.value = clean_name(t.value, 'hascolor')
        t.value = replace_colors_in_text(t.value)
        return t

    def t_HASTE(self, t):
        r'haste\(\d+\)'
        t.value = clean_name(t.value, 'haste')
        t.value = int(t.value)
        return t

    def t_INHERITABLE(self, t):
        r'inheritable(\(\))?'
        return t

    def t_LEADER(self, t):
        r'leader\(.+?\)'
        t.value = clean_name(t.value, 'leader')
        t.value = replace_colors_in_text(t.value)
        return t

    def t_NAME(self, t):
        r'name\([a-zA-Z0-9 ]+\)'
        t.value = clean_name(t.value, 'name')
        return t

    def t_ROW(self, t):
        r'row\([a-zA-Z]+\)'
        t.value = clean_name(t.value, 'row')
        t.value = replace_colors_in_text(t.value)
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

    def t_DELAY(self, t):
        r'delay\(\d+\)'
        t.value = clean_name(t.value, 'delay')
        t.value = int(t.value)
        return t

    def t_REMOVE(self, t):
        r'remove\([a-zA-Z0-9 ]+\)'
        t.value = t.value.replace('remove', '').strip('()')
        return t

    def t_CONVERT(self, t):
        r'convert\([a-zA-z, ]+\)'
        t.value = clean_name(t.value, 'convert')
        i = t.value.split(',')
        i[0] = replace_named_color(i[0]).lower()
        i[1] = replace_named_color(i[1]).lower()
        t.value = i
        return t

    def t_COMBO(self, t):
        r'combo\(\d+\)'
        t.value = clean_name(t.value, 'combo')
        t.value = int(t.value)
        return t

    def t_ABSORBNULL(self, t):
        r'absorbnull(\(\))?'
        return t

    def t_ATTABSORB(self, t):
        r'attabsorb(\(\))?'
        return t

    def t_SHIELD(self, t):
        r'shield\(\d+[\d%]\)'
        t.value = clean_name(t.value, 'shield')
        t.value = t.value.strip('%')
        t.value = int(t.value)
        return t

    t_ignore = ' \t\n'

    def t_error(self, t):
        raise rpadutils.ReportableError("Unknown text '%s'" % (t.value,))

    def build(self, **kwargs):
        # pass debug=1 to enable verbose output
        self.lexer = lex.lex(module=self)
        return self.lexer


class SearchConfig(object):

    def __init__(self, lexer):
        self.cd = None
        self.farmable = None
        self.haste = None
        self.inheritable = None
        self.shuffle = None
        self.unlock = None
        self.delay = None
        self.combo = None
        self.absorbnull = None
        self.attabsorb = None
        self.shield = None

        self.active = []
        self.board = []
        self.column = []
        self.color = []
        self.hascolor = []
        self.leader = []
        self.name = []
        self.row = []
        self.types = []
        self.remove = []
        self.convert = []

        for tok in iter(lexer.token, None):
            type = tok.type
            value = tok.value
            self.cd = self.setIfType('CD', type, self.cd, value)
            self.farmable = self.setIfType('FARMABLE', type, self.farmable, value)
            self.haste = self.setIfType('HASTE', type, self.haste, value)
            self.inheritable = self.setIfType('INHERITABLE', type, self.inheritable, value)
            self.shuffle = self.setIfType('SHUFFLE', type, self.shuffle, value)
            self.unlock = self.setIfType('UNLOCK', type, self.unlock, value)
            self.delay = self.setIfType('DELAY', type, self.delay, value)
            self.combo = self.setIfType('COMBO', type, self.combo, value)
            self.absorbnull = self.setIfType('ABSORBNULL', type, self.absorbnull, value)
            self.attabsorb = self.setIfType('ATTABSORB', type, self.attabsorb, value)
            self.shield = self.setIfType('SHIELD', type, self.shield, value)

            if type == 'ACTIVE':
                self.active.append(value)
            if type == 'BOARD':
                self.board.append(split_csv_orbcolors(value))
            if type == 'COLOR':
                self.color.append(assert_color(value))
            if type == 'COLUMN':
                self.column.append(assert_orbcolor(value))
            if type == 'HASCOLOR':
                self.hascolor.append(assert_color(value))
            if type == 'LEADER':
                self.leader.append(value)
            if type == 'NAME':
                self.name.append(value)
            if type == 'ROW':
                self.row.append(assert_orbcolor(value))
            if type == 'TYPE':
                if value not in TYPES:
                    raise rpadutils.ReportableError(
                        'Unexpected type {}, expected one of {}'.format(value, TYPES))
                self.types.append(value)
            if type == 'REMOVE':
                self.remove.append(value)
            if type == 'CONVERT':
                self.convert.append(value)

        self.filters = list()

        # Single
        if self.cd:
            self.filters.append(lambda m: m.search.active_min and m.search.active_min <= self.cd)

        if self.farmable:
            self.filters.append(lambda m: m.farmable_evo)

        if self.haste:
            text = "charge allies' skill by {}".format(self.haste)
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        if self.inheritable:
            self.filters.append(lambda m: m.is_inheritable)

        if self.shuffle:
            text = 'replace all'
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        if self.unlock:
            text = 'removes lock'
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        if self.delay:
            text = 'delay enemies for {}'.format(self.delay)
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        if self.combo:
            text = 'increase combo count by {}'.format(self.combo)
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        if self.convert:
            text_from = self.convert[0][0]
            text_to = self.convert[0][1]
            self.filters.append(lambda m,
                                       tf = text_from,
                                       tt = text_to:
                                (tf in m.search.orb_convert.keys()) if tf != 'any' else True and
                                (tt in m.search.orb_convert[tf]) if tt != 'any' else True)
            
        if self.absorbnull:
            text = 'damage absorb shield'
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        if self.attabsorb:
            text = 'att. absorb shield'
            self.filters.append(lambda m, t=text: t in m.search.active_desc)

        if self.shield:
            text = 'damage taken by {}%'.format(self.shield)
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

        if self.color:
            filters = []
            for ft in self.color:
                text = ft.lower()
                filters.append(lambda m, c=text: c in m.search.color)
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

        if self.hascolor:
            filters = []
            for ft in self.hascolor:
                text = ft.lower()
                filters.append(lambda m, c=text: c in m.search.hascolor)
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

        if self.remove:
            filters = []
            for ft in self.remove:
                text = ft.lower()
                filters.append(lambda m, t=text: t not in m.search.name)
            self.filters.append(self.or_filters(filters))

        if not self.filters:
            raise rpadutils.ReportableError('You need to specify at least one filter')

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
            raise rpadutils.ReportableError('You set {} more than once'.format(given_type))
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
        try:
            config = self._make_search_config(filter_spec)
        except Exception as ex:
            # Try to correct for missing closing tag
            try:
                config = self._make_search_config(filter_spec + ')')
            except:
                # If it still failed, raise the original exception
                raise ex
        pg_cog = self.bot.get_cog('PadGuide2')
        monsters = pg_cog.database.all_monsters()
        matched_monsters = list(filter(config.check_filters, monsters))

        # Removing entry with names that have gems in it
        rmvGemFilter = self._make_search_config('remove( gem)')
        matched_monsters = list(filter(rmvGemFilter.check_filters, matched_monsters))

        matched_monsters.sort(key=lambda m: m.monster_no_na, reverse=True)

        msg = []
        for page in range(0, int(len(matched_monsters) / 10) + 1):
            msg.append('Matched {} monsters'.format(len(matched_monsters)))
            if len(matched_monsters) > 10:
                msg[page] += ' (limited to 10)'  # Page {}'.format(page+1)
        n = 0
        for m in matched_monsters:
            msg[int(n / 10)] += '\n\tNo. {} {}'.format(m.monster_no_na, m.name_na)
            n += 1

        await self.bot.say(box(msg[0]))

    def _make_search_config(self, input):
        lexer = PadSearchLexer().build()
        lexer.input(input)
        return SearchConfig(lexer)

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



