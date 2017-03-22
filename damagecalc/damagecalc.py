import math

import discord
from discord.ext import commands
from ply import lex, yacc

from __main__ import user_allowed, send_cmd_help


class PadLexer(object):

    tokens = [
        'ROWS',
        'TPAS',
        'ATK',
#         'ID',
        'MULT',

#         'RESIST',
#         'DEFENCE',

        'ROW',
        'TPA',
        'ORB',
        'COMBO',
    ]

    def t_ROWS(self, t):
        r'rows\(\d+\)'
        t.value = t.value.strip('rows(').strip(')')
        t.value = int(t.value)
        return t

    def t_TPAS(self, t):
        r'tpas\(\d+\)'
        t.value = t.value.strip('tpas(').strip(')')
        t.value = int(t.value)
        return t

    def t_ATK(self, t):
        r'atk\(\d+\)'
        t.value = t.value.strip('atk(').strip(')')
        t.value = int(t.value)
        return t

    def t_ID(self, t):
        r'id\(\w+\)'
        t.value = t.value.strip('id(').strip(')')
        return t

    def t_MULT(self, t):
        r'multi?\([0-9.]+\)'
        t.value = t.value.strip('mult').strip('i').strip('(').strip(')')
        t.value = float(t.value)
        return t

    def t_ROW(self, t):
        r'row(\(\d*\))?'
        t.value = t.value.strip('row').strip('(').strip(')')
        t.value = int(t.value) if t.value else 6
        if t.value < 6 or t.value > 30:
            raise Exception('row must have 6-30 orbs, got ' + t.value)

        return t

    def t_TPA(self, t):
        r'tpa(\(\))?'
        t.value = 4
        return t

    def t_ORB(self, t):
        r'orbs?(\([0-9]*\))?'
        t.value = t.value.strip('orb').strip('s').strip('(').strip(')')
        t.value = int(t.value) if t.value else 3
        if t.value < 3 or t.value > 30:
            raise Exception('match must have 3-30 orbs, got ' + t.value)
        return t

    def t_COMBO(self, t):
        r'combos?\(\d+\)'
        t.value = t.value.strip('combo').strip('s').strip('(').strip(')')
        t.value = int(t.value)
        return t

    t_ignore = ' \t\n'

    def t_error(self, t):
        raise TypeError("Unknown text '%s'" % (t.value,))

    def build(self, **kwargs):
        # pass debug=1 to enable verbose output
        self.lexer = lex.lex(module=self)
        return self.lexer

class DamageConfig(object):

    def __init__(self, lexer):
        self.rows = None
        self.tpas = None
        self.atk = None
        self.id = None
        self.mult = None

        self.row_matches = list()
        self.tpa_matches = list()
        self.orb_matches = list()
        self.combos = None

        for tok in iter(lexer.token, None):
            type = tok.type
            value = tok.value
            self.rows = self.setIfType('ROWS', type, self.rows, value)
            self.tpas = self.setIfType('TPAS', type, self.tpas, value)
            self.atk = self.setIfType('ATK', type, self.atk, value)
            self.id = self.setIfType('ID', type, self.id, value)
            self.mult = self.setIfType('MULT', type, self.mult, value)

            if type == 'ROW':
                self.row_matches.append(value)
            if type == 'TPA':
                self.tpa_matches.append(value)
            if type == 'ORB':
                if value == 4:
                    self.tpa_matches.append(value)
                if value == 30:
                    self.row_matches.append(value)
                else:
                    self.orb_matches.append(value)

            self.combos = self.setIfType('COMBOS', type, self.combos, value)

        if self.rows is None:
            self.rows = 0
        if self.tpas is None:
            self.tpas = 0
        if self.atk is None:
            self.atk = 1
        if self.mult is None:
            self.mult = 1
        if self.combos is None:
            self.combos = 0

        if (len(self.row_matches) + len(self.tpa_matches) + len(self.orb_matches)) == 0:
            raise Exception('You need to specify at least one attack match')

    def setIfType(self, expected_type, given_type, current_value, new_value):
        if expected_type != given_type:
            return current_value
        if current_value is not None:
            raise Exception('You set {} more than once'.format(given_type))
        return new_value

    def updateWithMonster(self, monster):
        # set tpas
        # set attack
        # set mult
        pass

    def calculate(self):
        base_damage = 0
        for row_match in self.row_matches:
            base_damage += self.atk * (1 + (row_match - 3) * .25)
        for tpa_match in self.tpa_matches:
            base_damage += self.atk * (1 + (tpa_match - 3) * .25) * math.pow(1.5, self.tpas)
        for orb_match in self.orb_matches:
            base_damage += self.atk * (1 + (orb_match - 3) * .25)

        combo_count = len(self.row_matches) + len(self.tpa_matches) + len(self.orb_matches) + self.combos

        combo_mult = 1 + (combo_count - 1) * .25
        row_mult = 1 + self.rows / 10 * len(self.row_matches)

        final_damage = base_damage * combo_mult * row_mult * self.mult

        return int(final_damage)


class DamageCalc:
    """Damage calculator."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True)
    async def helpdamage(self, ctx):
        """Help info for the damage command

        ^damage <specification string>

        The specification string consists of a series of optional modifiers, followed by
        a minimum of at least one orb match.

        The optional modifiers are: rows(n), tpas(n), atk(n), mult(n)
        Any modifier left blank is assumed to be 1 or 0 as appropriate.

        The orb matches are any of: row(n), tpa(), orb(n), combo(n)
        The orb count for row/orb is optional; by default it will be 6/3.
        Minimum of 6/3 orbs for row/match, maximum of 30.
        Specifying 30 orbs automatically counts as a row, and 4 as a tpa.

        You can also leave off the () for row/tpa/orb.
        Use combo(n) to specify the non-damage combo count.

        A comprehensive example:
            rows(1) tpas(2) atk(100) mult(2.5) row row() row(8) tpa tpa() orb orb() orb(5) combo(2)

        This uses 1 RE, 2 TPAs, an attack of 100, a multiplier of 2.5 (total, not squared).
        Then it calculates damage for:
            two rows of 6 orbs
            one row of 8 orbs
            two tpas
            two matches of 3 orbs
            one match of 5 orbs
            two off-color matches

        Resistance, defense, loading by monster id, killers, etc coming soon
        """
        await send_cmd_help(ctx)

    @commands.command(pass_context=True)
    async def damage(self, ctx, *, damage_spec):
        """Computes damage for the provided damage_spec

        The specification string consists of a series of optional modifiers, followed by
        a minimum of at least one orb match.

        Use ^helpdamage for more info
        """

        lexer = PadLexer().build()
        lexer.input(damage_spec)
        config = DamageConfig(lexer)
        damage = config.calculate()
        await self.bot.say("`Damage: {}`".format(damage))


def setup(bot):
    n = DamageCalc(bot)
    bot.add_cog(n)
