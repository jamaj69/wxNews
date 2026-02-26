#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  8 13:44:14 2021

@author: jamaj
"""

from pygoogletranslation import Translator
import asyncio, aiohttp
# from aiogoogletrans import Translator

async def Translate(text):
    translator = Translator()
    trans_text = translator.translate(text, dest='pt')
    return trans_text.text

async def main():
    text="U.S. to relaunch small business pandemic aid program Monday with new fraud checks"    
    trans = await Translate(text)
    trans_text = trans
    print(trans)


if __name__ == "__main__":  
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())  