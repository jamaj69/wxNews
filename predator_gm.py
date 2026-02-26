#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Mar  4 07:49:10 2020

@author: jamaj
"""
import multiprocessing as mp
# import pandas as pd
# from pandas_datareader._utils import RemoteDataError
import csv
import psycopg2
import psycopg2.extras
import os
import sqlite3
import logging
import asyncio
from io import StringIO
import random
import requests
from aiohttp import ClientSession
import time
import sqlalchemy as sqla


# con = sqlite3.connect(":memory:")
# cur = con.cursor()
# cur.executescript("""
#     create table person(
#         firstname,
#         lastname,
#         age
#     );

#     create table book(
#         title,
#         author,
#         published
#     );

#     insert into book(title, author, published)
#     values (
#         'Dirk Gently''s Holistic Detective Agency',
#         'Douglas Adams',
#         1987
#     );
#     """)
# Load credentials from environment
from decouple import config
import os


def dbCredentials():
    """Return SQLite database path"""
    db_path = config('DB_PATH', default='predator_news.db')
    # Make path absolute if relative
    if not os.path.isabs(db_path):
        # Use script directory as base
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path


def OpenDB():
    conn_cred = {
        'host': 'localhost',
        'port': '5432',
        'dbname': 'predator3_dev',
        'user': 'postgres',
        'password': 'fuckyou'
    }
    
    uri = 'postgresql://{user}:{password}@{host}/{dbname}'.format(**conn_cred)
    engine = sqla.create_engine(uri)
    conn = engine.connect()
    return engine, conn    

def openSQlite(db_file=None,row_factory=sqlite3.Row):
    """ create a database connection to the SQLite database
        specified by db_file
    :param db_file: database file
    :return: Connection object or None
    """
    db_file = ':memory' if  db_file is None else db_file 
    conn = None
    try:
        conn = sqlite3.connect(db_file,check_same_thread=False,isolation_level = None)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        print(e)
    return conn
   
# def openSQlite(db_file=None):
#     """ create a database connection to the SQLite database
#         specified by db_file
#     :param db_file: database file
#     :return: Connection object or None
#     """
#     db_file = ':memory' if  db_file is None else db_file 
#     conn = None
#     try:
#         conn = sqlite3.connect(db_file)
#         return conn
#     except Error as e:
#         print(e)
#     return conn

def closeSQLite(conn):
    pass


def csv2df(cvs_text):
    print(cvs_text)
    try:
        csv = StringIO(cvs_text)
        csv.seek(0)
        df = pd.read_csv(csv,skipfooter=1, index_col=0)
        print("csv2df:",df)
        if df.shape[0] >1:
            return df
        else:
            return None
    except:
        return None

def List2db(cExch,engine, csv_list):
    CHUNCK = 200
    rec = csv_list[1:]
    for i in range(0, len(rec), CHUNCK):
        chunck = rec[i:i + CHUNCK]
        df = pd.DataFrame(chunck)
        df.to_sql('gm_eod_symbols1',engine, if_exists='append',index=False)
    return df


view1 = """CREATE VIEW cou_exch as 
    SELECT * FROM tb_iso_countries A, gm_eod_exch B 
    WHERE A.iso3 = B.iso_cou;"""

view2 = """CREATE VIEW symb_exch as 
          SELECT * FROM gm_eod_exch A, gm_eod_symbols B 
          WHERE B.exchange = A.exchcode;"""
sel1= """select distinct(exchange) 
        from gm_eod_symbols 
        where country = 'USA';"""

def create_tb_iso_countries(conn,lcreate=False,file='tb_iso_countries.tsv'):
    tb_name = 'tb_iso_countries'
    tb_columns = ['country','iso2','iso3','code','latitude','longitude','icon']
    tb_types = None
    sql1 =    """
        DROP TABLE IF EXISTS tb_iso_countries;
        CREATE TABLE tb_iso_countries (
            country     TEXT,
            iso2        TEXT,
            iso3        TEXT,
            code        TEXT,
            latitude 	TEXT,
            longitude	TEXT,
            icon        TEXT,
            PRIMARY KEY (iso3)
        );
        DROP INDEX IF EXISTS tb_iso_cou_idx;
        CREATE INDEX tb_iso_cou_idx 
            ON tb_iso_countries (code);
    """
    sql2 = 'SELECT * FROM {};'.format(tb_name)
    sql = sql1 if lcreate else sql2
    print('Executando sql: %s' % sql)
    c = conn.cursor()
    c.executescript(sql)
    conn.commit()
    if lcreate:
        print('A recriar a tabela tb_iso_countries')
        lskip = True
        f = open(file)
        lfstrow = True
        for row in csv.reader(f,delimiter='\t'):
            lfstrow = False
            if not (lfstrow and lskip):
                values = tuple(row) 
                sql = 'INSERT INTO {}{} VALUES {}'.format(tb_name,tuple(tb_columns),values)
                print(sql)
                c.execute(sql)
        f.close        
        conn.commit()
    
    c.close()
    return tb_columns, tb_types

    
def create_tb_eod_exch(conn,lcreate=False,file='exchanges_0000.tsv'):
    tb_name = 'gm_eod_exch'
    tb_columns = ['exchcode','mic','exchname','iso_cou','iso_cur','iso_cur1',
                  'iso_cur2','iso_cur3']
    tb_types = None
    sql1 =    """
        DROP TABLE IF EXISTS gm_eod_exch;
        CREATE TABLE gm_eod_exch (
            exchcode    TEXT,
            mic         TEXT,
            exchname    TEXT, 
            iso_cou     TEXT,
            iso_cur     TEXT,
            iso_cur1    TEXT,
            iso_cur2    TEXT,
            iso_cur3    TEXT,
            gm_imp_tick INTEGER DEFAULT 0,
            gm_imp_ts_1 INTEGER DEFAULT 0,
            gm_imp_ts_2 INTEGER DEFAULT 0,
            PRIMARY KEY (exchcode)
        );
        DROP INDEX IF EXISTS eod_exch_idx;
        CREATE INDEX eod_extg_idx 
            ON gm_eod_exch (gm_imp_tick,gm_imp_ts_1,gm_imp_ts_2);
    """
    sql2 = 'SELECT * FROM {};'.format(tb_name)
    sql = sql1 if lcreate else sql2
    print('Executando sql: %s' % sql)
    c = conn.cursor()
    c.executescript(sql)
    conn.commit()
    
    if lcreate:
        print('A recriar a tabela tb_iso_countries')
        lskip = True
        f = open(file)
        lfstrow = True
        for row in csv.reader(f,delimiter='\t'):
            lfstrow = False
            if not (lfstrow and lskip):
                values = tuple(row) 
                sql = 'INSERT INTO {}{} VALUES {}'.format(tb_name,tuple(tb_columns),values)
                print(sql)
                c.execute(sql)
        f.close        
        conn.commit()
   
    c.close()
    return tb_columns, tb_types

def ins_tb_eod_exch(conn,tb_name = 'gm_eod_exch', tb_columns = None, tb_types = None,tb_values=None):
    sql = 'INSERT INTO {}{} VALUES {}'.format(tb_name,tuple(tb_columns),tuple(tb_values))
    print(sql)
    return sql 

def create_tb_eod_sym(conn,lcreate=False, file='gm_eod_symbols.tsv'):
    tb_name = 'gm_eod_symbols'
    tb_columns = ['code','name','country','exchange','currency','type']
    tb_types = ['TEXT','TEXT','TEXT','TEXT','TEXT','TEXT' ]
    sql1 =    """
        DROP TABLE IF EXISTS gm_eod_symbols;
        CREATE TABLE gm_eod_symbols (
            code           TEXT NOT  NULL,
            name           TEXT NOT NULL,
            country        TEXT,
            iso_cou        TEXT NOT NULL,
            exchange       TEXT NOT NULL,
            exchcode       TEXT NOT NULL,
            currency       TEXT,
            type           TEXT,
            symbolcode     TEXT NOT  NULL,
            gmtoffset      INTEGER DEFAULT 0,
            gm_imp_tick    INTEGER DEFAULT 0,
            gm_imp_ts_1    INTEGER DEFAULT 0,
            gm_imp_ts_2    INTEGER DEFAULT 0,
            gm_imp_intra   INTEGER DEFAULT 0,
            PRIMARY KEY(code,exchcode)
       );      
       DROP INDEX IF EXISTS eod_symbols_idx;
       CREATE INDEX eod_symbols_idx 
            ON gm_eod_symbols (code,exchcode);
    """
    sql2 = 'SELECT * FROM {};'.format(tb_name)
    sql = sql1 if lcreate else sql2
    print('Executando sql: %s' % sql)
    c = conn.cursor()
    c.executescript(sql)
    conn.commit()
    
    if lcreate:
        print('A recriar a tabela tb_iso_countries')
        lskip = True
        f = open(file)
        lfstrow = True
        for row in csv.reader(f,delimiter='\t'):
            lfstrow = False
            if not (lfstrow and lskip):
                values = tuple(row) 
                sql = 'INSERT INTO {}{} VALUES {}'.format(tb_name,tuple(tb_columns),values)
                print(sql)
                c.execute(sql)
        f.close        
        conn.commit()
   
    c.close()
    return tb_columns, tb_types

def create_tb_eod_opt(conn,lcreate=False):
    tb_name = 'gm_eod_options'   
    tb_columns = ['code','name','country','exchange','currency','type']
    tb_types = ['TEXT','TEXT','TEXT','TEXT','TEXT','TEXT' ]
    sql1 =    """
        DROP TABLE IF EXISTS gm_eod_options;
        CREATE TABLE gm_eod_options (
            code                  TEXT,
            name                  TEXT,
            country               TEXT,
            exchange              TEXT,
            currency              TEXT,
            type                  TEXT
        );
        CREATE [UNIQUE] INDEX unique_index 
        ON {tb_name}(column_list);
    """
    sql2 = 'SELECT * FROM %s' % tb_name
    sql = sql1 if lcreate else sql2
    c.executescript(sql)
    conn.commit()
    c.close()
    return tb_columns, tb_types

def sqlEODTicks():
    sql =    """
        DROP TABLE IF EXISTS gm_eod_ticks;
        CREATE TABLE gm_eod_ticks (
            code            TEXT    NOT NULL,
            timestamp       INTEGER NOT NULL,
            gmtoffset       INTEGER DEFAULT 0,
            datetime        TEXT    DEFAULT NULL,
            open            REAL    DEFAULT 0,
            high            REAL    DEFAULT 0,
            low             REAL    DEFAULT 0,
            close           REAL    DEFAULT 0,
            volume          INTEGER DEFAULT 0,
            adj_close       REAL    DEFAULT 0,
           	prev_close      REAL    DEFAULT 0,
           	change          REAL    DEFAULT 0,
           	change_p        REAL    DEFAULT 0,
            lastupdate      INTEGER NOT NULL,
            PRIMARY KEY(code,timestamp) ON CONFLICT IGNORE
        ); 
        DROP INDEX IF EXISTS eod_ticks_idx;
        CREATE UNIQUE INDEX eod_ticks_idx 
            ON gm_eod_ticks (code,timestamp);
    """
    return sql

def create_tb_eod_intra(conn,lcreate=False):
    tb_name = 'gm_eod_ticks'     
    tb_columns  = ['timestamp','gmtoffset','datetime','open','high','low','close','adj_close'     ,'volume']
    tb_colEOD   = ['Timestamp','Gmtoffset','Datetime','Open','High','Low','Close','Adjusted_close','Volume']
    tb_types = None
    c = conn.cursor()
    sql1 = sqlEODTicks()
    sql2 = 'SELECT * FROM %s' % tb_name
    sql = sql1 if lcreate else sql2
    print('Executando sql: %s' % sql)
    c.executescript(sql)
    conn.commit()
    c.close()
    return tb_columns, tb_types, tb_colEOD

def create_tb_eod_ticks(conn,lcreate=False):
    tb_name = 'gm_eod_ticks'   
    tb_columns  = ['code','timestamp','gmtoffset','open','high','low','close','volume','prev_close'   ,'change','change_p']
    tb_colEOD   = ['code','timestamp','gmtoffset','open','high','low','close','volume','previousClose','change','change_p']
    tb_types = ['TEXT','TEXT','TEXT','TEXT','TEXT','TEXT' ]
    c = conn.cursor()
    sql1 = sqlEODTicks()
    sql2 = 'SELECT * FROM %s' % tb_name
    sql = sql1 if lcreate else sql2
    print('Executando sql: %s' % sql)
    c.executescript(sql)
    conn.commit()
    c.close()
    return tb_columns, tb_types, tb_colEOD

def create_tb_eod_hist(conn,lcreate=False):
    tb_name = 'gm_eod_ticks'   
    tb_columns  = ['datetime','open','high','low','close', 'adj_close'    ,'volume']
    tb_colEOD   = ['Date'   ,'Open','High','Low','Close','Adjusted_close','Volume']
    c = conn.cursor()
    sql1 = sqlEODTicks()
    sql2 = 'SELECT * FROM %s' % tb_name
    sql = sql1 if lcreate else sql2
    print('Executando sql: %s' % sql)
    c.executescript(sql)
    conn.commit()
    c.close()
    return tb_columns, tb_types, tb_colEOD

def generateSQLInsert(table_name,keys, vals):
    k = list(map(eval, keys)) 
    v = list(map(eval, vals)) 
    sql = 'INSERT INTO {} {} VALUES {} ;'.format(table_name,k,v)
    return(sql)


def save_tsv(varname,vardata):
    ext= '.tsv'
    filename= '{fname}{ext}'.format(fname=varname,ext=ext)
    print('save_tsv: %s'%filename)
    f=open(filename,'wb+')
    f.write(vardata)
    f.close()    

 
def ImportSymbolos(cExchCode,engine, df):
    print('Importando dados de %s '%cExchCode )
    print(df)
    # df.to_sql('gm_eod_symbols',engine, if_exists='append',index=False)
    
    
def load_tsv( varname, engine_params=None):
    pwd=os.getcwd()
    engine_params = {
                            'pwd'  : pwd,
                            'ext'  : '.tsv',
                            'sep'  : '\t'
                        }
    ext= '.tsv'
    filename= '{pwd}{varname}{ext}'.format(pwd=pwd,varname=varname,ext=ext)
    f=f=open(filename,'r')
    tsv = f.read(f)
    f.close()    
    return(tsv)

def load_csv( varname, engine_params=None):
    engine_params = {
                            'pwd'  : _get_pwd(),
                            'ext'  : '.csv',
                            'sep'  : ','
                        }
    ext= '.csv'
    filename= "{pwd}{varname}{ext}".format((pwd,varname,ext))
    f=open(filename,'r')
    csv = f.read(f)
    f.close()    
    return(csv)
   
def load_json(varname, vardata, engine_params=None):
    pwd=os.getcwd()
    engine_params= {
                            'pwd' : pwd,
                            'ext' : '.json'
                            }
    ext= '.json'
    filename= '{pwd}/{fname}{ext}'.format(pwd=pwd,fname=varname,ext=ext)
    f=open(filename,'r')
    data = f.read()
    print(filename)
    vardata=json.loads(data)
    f.close()    
    return(vardata)

def save_json(varname,vardata):
    pwd=os.getcwd()
    ext= '.json'
    filename= '{pwd}/{fname}{ext}'.format(pwd=pwd,fname=varname,ext=ext)
    print('save_json: %s'%filename)
    f=open(filename,'wb+')
    f.write(vardata)
    f.close()    

def save_csv(varname,vardata):
    pwd=os.getcwd()
    ext= '.tsv'
    filename= '{pwd}/{fname}{ext}'.format(pwd=pwd,fname=varname,ext=ext)
    print('save_csv: %s'%filename)
    f=open(filename,'wb+')
    f.write(vardata)
    f.close()    

def get_http():
    pass

def get_sqlite():
    pass

def json_walk(d,path=['/'],nivel=0):
    print("lvl%d path:%s"%(nivel,path))
    i = 0
    nivel = nivel +1
    print("nivel %d"%nivel)
    for k,v in d.items():
        i = i + 1
        print(path)
        path.append(k)
        if isinstance(v, str) or isinstance(v, int) or isinstance(v, float):
            # print("{}={}".format(".".join(path), k)) 
            pass
        elif v is None:
            pass
        elif isinstance(v, list):
            print("item de dict é list")
            # print(nivel)
            print(k)
            # print("{}={}".format(".".join(path), k)) 
            n=0
            for item in v:
#                print(n)
                path.append(str(n))
                if isinstance(item, list):
                    print(item)
                elif isinstance(item, dict):
#                    print("item de lista é dict. NIVEL %d"%nivel)
                    if  nivel == 4:  
                        json_walk(item,path,nivel,)
                        # print(item)
                        pass
                    else:
                        # nivel = nivel +1
                        json_walk(item,path,nivel,)
                        # nivel = nivel -1
                else:
                    print("{}={}".format(".".join(path), item)) 
                    pass
                n = n+1
                path.pop()
        elif isinstance(v, dict):
            print("item de dict é dict")
            # print(k)
#            print(nivel)
            # path.append(k)
            nivel = nivel +1
            print("{}={}".format(".".join(path), k)) 
            json_walk(v,path,nivel)
            nivel = nivel -1
            # path.pop()
        else:           
            print("###Type {} not recognized: {}.{}={}".format(type(v), ".".join(path),k, v))
        path.pop()
    
async def load(varname, engine= None, engine_params=None ):
    engines = {
                'engine': 'default','task':load_tsv,
                'engine':'csv','task':load_csv,
                'engine':'tsv','task':load_tsv,
                'engine':'json','task':load_json,
                'engine':'http','task':get_http,
                'engine':'sqlite','task':get_sqlite,
               }
    varname = load_json(varname, engine_params)
    return varname

if __name__ == '__main__':
    mp.freeze_support()
