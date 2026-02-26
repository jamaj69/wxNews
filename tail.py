#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May 26 15:39:47 2020

@author: jamaj
"""
import asyncio


import time
def follow(thefile, target):
#    thefile.seek(0,2)      # Go to the end of the file
    thefile.seek(0)      # Go to the end of the file
    while True:
         line = thefile.readline()
         if not line:
             time.sleep(0.1)    # Sleep briefly
             continue
         target.send(line)

# A filter.
async def grep(pattern,target):
    while True:
        line = (yield)           # Receive a line
        if pattern in line:
            target.send(line)    # Send to next stage

# A sink.  A coroutine that receives data
async def printer():
    while True:
         line = (yield)
         print(line)

# Example use
if __name__ == '__main__':
    f = open("/var/log/kern.log")
    follow(f,
           grep('ACPI',
           printer()))