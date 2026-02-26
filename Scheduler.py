#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 30 19:54:45 2020

@author: jamaj
"""

import datetime
import time
import sys
# from blist import blist,sortedlist  # Not used, removed dependency
import asyncio
import async_timeout
import feedparser
import aiohttp
import functools
import pprint
import json
   


import urllib


from dateutil import parser, tz
from dateutil.tz import UTC


tz_str = '''-12 Y
-11 X NUT SST
-10 W CKT HAST HST TAHT TKT
-9 V AKST GAMT GIT HADT HNY
-8 U AKDT CIST HAY HNP PST PT
-7 T HAP HNR MST PDT
-6 S CST EAST GALT HAR HNC MDT
-5 R CDT COT EASST ECT EST ET HAC HNE PET
-4 Q AST BOT CLT COST EDT FKT GYT HAE HNA PYT
-3 P ADT ART BRT CLST FKST GFT HAA PMST PYST SRT UYT WGT
-2 O BRST FNT PMDT UYST WGST
-1 N AZOT CVT EGT
0 Z EGST GMT UTC WET WT
1 A CET DFT WAT WEDT WEST
2 B CAT CEDT CEST EET SAST WAST
3 C EAT EEDT EEST IDT MSK
4 D AMT AZT GET GST KUYT MSD MUT RET SAMT SCT
5 E AMST AQTT AZST HMT MAWT MVT PKT TFT TJT TMT UZT YEKT
6 F ALMT BIOT BTT IOT KGT NOVT OMST YEKST
7 G CXT DAVT HOVT ICT KRAT NOVST OMSST THA WIB
8 H ACT AWST BDT BNT CAST HKT IRKT KRAST MYT PHT SGT ULAT WITA WST
9 I AWDT IRKST JST KST PWT TLT WDT WIT YAKT
10 K AEST ChST PGT VLAT YAKST YAPT
11 L AEDT LHDT MAGT NCT PONT SBT VLAST VUT
12 M ANAST ANAT FJT GILT MAGST MHT NZST PETST PETT TVT WFT
13 FJST NZDT
11.5 NFT
10.5 ACDT LHST
9.5 ACST
6.5 CCT MMT
5.75 NPT
5.5 SLT IST
4.5 AFT IRDT
3.5 IRST
-2.5 HAT NDT
-3.5 HNT NST NT
-4.5 HLV VET
-9.5 MART MIT'''

tzd = {}
for tz_descr in map(str.split, tz_str.split('\n')):
    tz_offset = int(float(tz_descr[0]) * 3600)
    for tz_code in tz_descr[1:]:
        tzd[tz_code] = tz_offset


# def Norm_DateTime(dt):
#     pa = parser.parse(dt,tzinfos=tzd,fuzzy_with_tokens=True)
#     data = pa[0].astimezone(UTC)
#     return data.isoformat()

def Norm_DateTime(dt):
    pa = parser.parse(dt,tzinfos=tzd,fuzzy_with_tokens=True)
    data = pa[0].astimezone(UTC)
    time = data.time()
    data_at = datetime.datetime.now().date()
    ret = data    
    if data.day <= 12:
        valid = datetime.date(day=data.month,month=data.day,year=data.year)
        dif1 = (valid - data_at).days
        dif2 = (data.date() - data_at).days
        if dif1 < dif2:
            ret = datetime.datetime(day=valid.month,month=valid.day,year=valid.year,hour=time.hour,minute=time.minute,second=time.second)
    return ret.isoformat()

def GetShortURL(curl):
    parts = urllib.parse.urlsplit(curl)
    # print('GetShortURL({curl}). parts: {parts}'.format(curl=curl,parts=parts))
    netloc = parts.netloc
    path = parts.path
    query = parts.query

    a = netloc.replace('.','_')
    b = path.replace('/','_')

    c = b[:64]

    return (a+c) 



def json_write(json_file,data):
    with open(json_file, 'w') as outfile:
        json.dump(data, outfile)
    return(data)

def json_read(json_file):
    with open(json_file) as json_file:
        data = json.load(json_file)
    return(data)


async def fetch(session,url=None,TIMEOUT=30, HEADERS = {'User-Agent': 'Mozilla/5.0'} ):
    res = {}
    res['url'] = url
    res['error'] = ""
    res['text'] = ""
    res['stat'] = 0
            
    with async_timeout.timeout(TIMEOUT):
       try:
           async with session.get(url,headers=HEADERS) as response:
               res['stat']  = response.status
               # print("Headers:  ",response.headers)
               res['text']  = await response.text()            
       except aiohttp.ClientConnectorError as e:
           error= 'Connection Error. url: {url}. error: {error}'.format(url=url,error=str(e))
           res['error']  = error            
       except asyncio.TimeoutError as e:
           error= 'Timeout Error. url: {url}. error: {error}'.format(url=url,error=str(e))
           res['error']  = error            
       except Exception as e:
           error = 'Error. url: {url}. error: {error}'.format(url=url,error=e.__class__)
           res['error']  = error            
       finally:
           return res

class Scheduler:
    aTasks =  []
    ptasks  = []
    torun   = []
    running = []
    ended   = []
    
    def __init__(self):
        pass
        
    def schedule_task(self,func,params=None):
        print('schedule_task {func}'.format(func=func.__qualname__))
        task = Task(func,params=params,control=self)
        Scheduler.ptasks.append(task)

        print('Adicionada uma task ptasks', task)
        print('JobStatus (system):{0}'.format(len(Scheduler.ptasks)))
        print('JobStatus (pending):{0}'.format(len(Scheduler.torun)))
        print('JobStatus (running):{0}'.format(len(Scheduler.running)))
        print('JobStatus (ended):{0}'.format(len(Scheduler.ended)))
        return task

    def add_task(self,func,params=None):
        print('add task')
        task = Task(func,params=params,control=self)
        Scheduler.torun.append(task)

        print('Adicionada uma task torun', task)
        print('JobStatus (system):{0}'.format(len(Scheduler.ptasks)))
        print('JobStatus (pending):{0}'.format(len(Scheduler.torun)))
        print('JobStatus (running):{0}'.format(len(Scheduler.running)))
        print('JobStatus (ended):{0}'.format(len(Scheduler.ended)))
        # cls.aTasks.append(task)
        return task        

    @classmethod
    async def runtasks(self,tasks):
        # print('runtasks tasks:',tasks)
        Scheduler.ChangeStatusRun(tasks)
        task_group = [ task.run() for task in tasks ]
        res = await asyncio.gather(*task_group)
        Scheduler.ChangeStatusEnd(tasks)
        return res
 
    @classmethod
    def ChangeStatusRun(self,tasks):        
        for task in tasks:
            Scheduler.torun.remove(task)
            Scheduler.running.append(task)
        # Scheduler.running += tasks
        print('Adicionada {n} tasks em running'.format(n=len(tasks)), tasks)
        print('JobStatus (system):{0}'.format(len(Scheduler.ptasks)))
        print('JobStatus (pending):{0}'.format(len(Scheduler.torun)))
        print('JobStatus (running):{0}'.format(len(Scheduler.running)))
        print('JobStatus (ended):{0}'.format(len(Scheduler.ended)))
        # Scheduler.torun.remove(tasks)
        
    @classmethod
    def ChangeStatusEnd(self,tasks):
        # Scheduler.ended += tasks

        for task in tasks:
            Scheduler.running.remove(task)
            Scheduler.ended.append(task)

        # Scheduler.running.remove(tasks)

    
    def JobStatus(self):
        print('JobStatus (system):{0}'.format(len(Scheduler.ptasks)))
        tasks = Scheduler.ptasks
        for task in tasks:
            print('--',task) 
        print('JobStatus (pending):{0}'.format(len(Scheduler.torun)))
        print('JobStatus (running):{0}'.format(len(Scheduler.running)))
        print('JobStatus (ended):{0}'.format(len(Scheduler.ended)))

        return (Scheduler.ptasks, Scheduler.torun, Scheduler.running, Scheduler.ended)  
        
    async def run(self):        
        print('Scheduler.run(): begin')

        # system_tasks = Task(func=self.run_system_tasks,params=None,control=self)
        # Scheduler.ptasks.append(system_tasks)
        # user_tasks = Task(func=self.run_user_tasks,params=None,control=self)
        # Scheduler.ptasks.append(user_tasks)
        # res = await self.runtasks(tasks=Scheduler.ptasks)
              
        system_task = asyncio.create_task(self.run_system_tasks())
        user_task   = asyncio.create_task(self.run_user_tasks())
        task_group = [ system_task, user_task ]
        print('Scheduler.run(): init')
        # Scheduler.ChangeStatusRun(task_group)
        
        res = await asyncio.gather(*task_group)
        
        # Scheduler.ChangeStatusEnd(task_group)
        print('Scheduler.run(): end')
        return res
    
    @classmethod
    async def run_system_tasks(self, params=None, control=None):
        system_tasks =  Scheduler.ptasks  
        pending = [ task.run() for task in system_tasks]
        res = None
        print('Scheduler.run_system_tasks(): init')

        res = await asyncio.gather(*pending)
        # done, pending = await asyncio.wait(pending,return_when=asyncio.ALL_COMPLETED)

        print('Scheduler.run_system_tasks(): end')

        # print('Scheduler.run_system_tasks(): end. When fisrt completed')
        # for coro in done:
        #     res = await coro
        #     print('Result: ', res)            
        return res


    @classmethod
    async def run_user_tasks(self, params=None, control=None):
        print('Scheduler.run_user_tasks(): init')
        lstop = True
        results  = None
        while not lstop:    
            torun_tasks  = Scheduler.torun
            if len(torun_tasks) > 0:
                print("run_user_tasks. torun > 0!")
                task_group = [ task.run() for task in torun_tasks]
                results = await asyncio.gather(*task_group)
            else:
                print("run_user_tasks. torun > 0!")
                await asyncio.sleep(1)
            lstop = False
        print('Scheduler.run_user_tasks(): end')
        return results
 
    def __str__(self):
        return "Scheduler()"

    def __repr__(self):
        return "Scheduler()"
 
       
class Task:
    task_id = 0
    def __init__(self,func,params=None, control=None):
        # Necessários para comporação e identificação de cada tarefa Task
        Task.task_id += 1
        self.id = Task.task_id
        self.ts = datetime.datetime.now().timestamp()

        self.func = func
        self.params = params
        self.status  = 0
        self.control = control
        self.aVars = {}
        self.karma = 0
        
    def run(self):
        task = asyncio.create_task(self.func(params = self.params,control=self)) 
        return task

    def Get(self,var):
        print("Valor de {var} = {val}".format(var=var,val=self.aVars[var]))
        return self.aVars[var]
 
    def Set(self,var,val):
        self.aVars[var] = val
        # print("Valor de {var} = {val}".format(var=var,val=self.aVars[var]))
        return val
        
    def add_task(self,func,params=None):
        return self.control.add_task(func,params)

    async def runtasks(self,tasks):
        return await self.control.runtasks(tasks)

    def JobStatus(self):
        jobstat = self.control.JobStatus()
        return jobstat

    def __gt__(self, other):
        if not isinstance(other,Task):
            raise Exception("Task are only comparable to Task, not to {0}".format(type(other)))
        else:
            return self.ts.__gt__(other.ts)

    def __lt__(self, other):
        if not isinstance(other,Task):
            raise Exception("Task are only comparable to Task, not to {0}".format(type(other)))
        else:
            return self.ts.__lt__(other.ts)

    def __str__(self):
        return "Task(id={id},func={function},params={params},control={control})".format(id=self.id,function=self.func.__qualname__,params="self.params",control=self.control)
 
    def __repr__(self):
        return "Task(id={id},func={function},params={params},control={control}),ts = {ts} |".format(id=self.id,function=self.func.__qualname__,params="self.params",control=self.control, ts= self.ts)
 
        
 

# class Control:
#     scheduler = Scheduler()
#     def __init__(self):
#         pass    
#     def schedule_task(self,task):
#         Control.scheduler.schedule_p_task(task)
#     def Get(self,varname):
#         return False
#         pass
#     def GetTasks(self):
#         pass
#     async def run(self):
#         res = await Control.scheduler.run()
#         return res
#     async def runtasks(self,Task_list):            
#         res = await Control.scheduler.runtasks(Task_list)
#         return res
    
