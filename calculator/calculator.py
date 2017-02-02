from math import *
from random import *
import re

import discord
from discord.ext import commands
from cogs.utils.chat_formatting import *

ACCEPTED_TOKENS = r'[\[\]\-()*+/0-9=.,%>< ]|random|randint|choice|randrange|True|False|if|and|or|else|is|acos|acosh|asin|asinh|atan|atan2|atanh|ceil|copysign|cos|cosh|degrees|e|erf|erfc|exp|expm1|fabs|factorial|floor|fmod|frexp|fsum|gamma|gcd|hypot|inf|isclose|isfinite|isinf|isnan|ldexp|lgamma|log|log10|log1p|log2|modf|nan|pi|pow|radians|sin|sinh|sqrt|tan|tanh'

HELP_MSG = '''
This calculator works by first validating the content of your query against a whitelist, and then
executing a python eval() on it, so some common syntax wont work. Notably, you have to use
pow(x, y) instead of x^y. Here is the full symbol whitelist:
'''

class Calculator:
    def __init__(self, bot):
        self.bot = bot

    @commands.group(pass_context=True)
    async def helpcalc(self, context):
        '''Whispers info on how to use the calculator.'''
        help_msg = HELP_MSG + '\n' + ACCEPTED_TOKENS
        await self.bot.whisper(box(help_msg))

    @commands.group(pass_context=True, name='calculator', aliases=['calc'])
    async def _calc(self, context, *, input):
        '''Use helpcalc for more info.'''
        bad_input = list(filter(None, re.split(ACCEPTED_TOKENS, input)))
        if len(bad_input):
            err_msg = 'Found unexpected symbols inside the input: {}'.format(bad_input)
            help_msg = 'Use [p]helpcalc for info on how to use this command'
            await self.bot.say(inline(err_msg + '\n' + help_msg))
            return

        calculate_stuff = eval(input)
        if len(str(calculate_stuff)) > 0:
            em = discord.Embed(color=discord.Color.blue(), description='**Input**\n`{}`\n\n**Result**\n`{}`'.format(input, calculate_stuff))
            await self.bot.say(embed=em)


def setup(bot):
    bot.add_cog(Calculator(bot))
