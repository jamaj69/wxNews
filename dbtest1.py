#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Mar 19 21:17:20 2020

@author: jamaj
"""
from sqlalchemy import (create_engine, Table, Column, Integer, 
    String, MetaData)
from sqlalchemy import inspect
from predator_gm import dbCredentials

conn = dbCredentials()
eng = create_engine('postgresql+psycopg2://{user}:{password}@{host}/{dbname}'.format(**conn))
cur = eng.connect()
  
meta = MetaData()
meta.reflect(bind=eng)

for table in meta.tables:
    print(table)

insp = inspect(eng)

tables = insp.get_table_names()
print("Tables:", tables)

for table in tables:    
    print("table:",table,"\n","Columns: ", insp.get_columns(table))
    print("Constraints:\n",insp.get_pk_constraint(table))

print(insp.get_schema_names())
