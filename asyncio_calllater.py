#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr  7 03:42:32 2020

@author: jamaj
"""


import asyncio
loop = asyncio.get_event_loop()

def hello():
    loop.call_later(3, print_hello)

def print_hello():
    print('Hello!')
    loop.call_later(3, hello)
    
if __name__ == '__main__':
    loop.call_soon(hello)
    loop.run_forever()