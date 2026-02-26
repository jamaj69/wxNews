#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Mar 24 09:42:01 2020

@author: jamaj
"""   

import wx
import wx.grid as Grid
import random

import images
import logging
import sys
from multiprocessing import Queue
#from wxasync import AsyncBind, WxAsyncApp, StartCoroutine
#import asyncio, aiohttp
#from asyncio.events import get_event_loop

from sqlalchemy import (create_engine, Table, Column, Integer, 
    String, MetaData, Text)
from sqlalchemy import inspect,select,desc
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.sql import func
import os

# Load credentials from environment
from decouple import config


def dbCredentials():
    """Return SQLite database path"""
    db_path = config('DB_PATH', default='predator_news.db')
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path




#---------------------------------------------------------------------------

class MegaTable(Grid.GridTableBase):
    """
    A custom wx.Grid Table using user supplied data
    """
    def __init__(self, data, colnames, rowlabelscol, plugins):
        """data is a list of the form
        [(rowname, dictionary),
        dictionary.get(colname, None) returns the data for column
        colname
        """
        # The base class must be initialized *first*
        Grid.GridTableBase.__init__(self)
        self.data = data
        self.colnames = colnames
        self.plugins = plugins or {}
        self.labelsgen = rowlabelscol
        # XXX
        # we need to store the row length and column length to
        # see if the table has changed size
        self._rows = self.GetNumberRows()
        self._cols = self.GetNumberCols()

    def GetNumberCols(self):
        return len(self.colnames)

    def GetNumberRows(self):
        return len(self.data)

    def GetColLabelValue(self, col):
        return self.colnames[col]

    def GetRowLabelValue(self, row):
        # return "row %03d" % int(self.data[row][0])
        return self.labelsgen(self.data[row],row)

    def GetValue(self, row, col):
        # return str(self.data[row][1].get(self.GetColLabelValue(col), ""))
        return str(self.data[row].get(self.GetColLabelValue(col), ""))

    def GetRawValue(self, row, col):
        # return self.data[row][1].get(self.GetColLabelValue(col), "")
        return self.data[row].get(self.GetColLabelValue(col), "")

    def SetValue(self, row, col, value):
        # self.data[row][1][self.GetColLabelValue(col)] = value
        self.data[row][self.GetColLabelValue(col)] = value

    def ResetView(self, grid):
        """
        (Grid) -> Reset the grid view.   Call this to
        update the grid if rows and columns have been added or deleted
        """
        grid.BeginBatch()

        for current, new, delmsg, addmsg in [
            (self._rows, self.GetNumberRows(), Grid.GRIDTABLE_NOTIFY_ROWS_DELETED, Grid.GRIDTABLE_NOTIFY_ROWS_APPENDED),
            (self._cols, self.GetNumberCols(), Grid.GRIDTABLE_NOTIFY_COLS_DELETED, Grid.GRIDTABLE_NOTIFY_COLS_APPENDED),
        ]:

            if new < current:
                msg = Grid.GridTableMessage(self,delmsg,new,current-new)
                grid.ProcessTableMessage(msg)
            elif new > current:
                msg = Grid.GridTableMessage(self,addmsg,new-current)
                grid.ProcessTableMessage(msg)
                self.UpdateValues(grid)

        grid.EndBatch()

        self._rows = self.GetNumberRows()
        self._cols = self.GetNumberCols()
        # update the column rendering plugins
        self._updateColAttrs(grid)

        # update the scrollbars and the displayed part of the grid
        grid.AdjustScrollbars()
        grid.ForceRefresh()


    def UpdateValues(self, grid):
        """Update all displayed values"""
        # This sends an event to the grid table to update all of the values
        msg = Grid.GridTableMessage(self, Grid.GRIDTABLE_REQUEST_VIEW_GET_VALUES)
        grid.ProcessTableMessage(msg)

    def _updateColAttrs(self, grid):
        """
        wx.Grid -> update the column attributes to add the
        appropriate renderer given the column name.  (renderers
        are stored in the self.plugins dictionary)
        Otherwise default to the default renderer.
        """
        col = 0

        for colname in self.colnames:
            attr = Grid.GridCellAttr()
            if colname in self.plugins:
                renderer = self.plugins[colname](self)

                if renderer.colSize:
                    grid.SetColSize(col, renderer.colSize)

                if renderer.rowSize:
                    grid.SetDefaultRowSize(renderer.rowSize)

                attr.SetReadOnly(True)
                attr.SetRenderer(renderer)

            grid.SetColAttr(col, attr)
            col += 1

    # ------------------------------------------------------
    # begin the added code to manipulate the table (non wx related)
    def AppendRow(self, row):
        #print('append')
        entry = {}

        for name in self.colnames:
            entry[name] = "Appended_%i"%row

        # XXX Hack
        # entry["A"] can only be between 1..4
        entry["A"] = random.choice(range(4))
        self.data.insert(row, ["Append_%i"%row, entry])

    def DeleteCols(self, cols):
        """
        cols -> delete the columns from the dataset
        cols hold the column indices
        """
        # we'll cheat here and just remove the name from the
        # list of column names.  The data will remain but
        # it won't be shown
        deleteCount = 0
        cols = cols[:]
        cols.sort()

        for i in cols:
            self.colnames.pop(i-deleteCount)
            # we need to advance the delete count
            # to make sure we delete the right columns
            deleteCount += 1

        if not len(self.colnames):
            self.data = []

    def DeleteRows(self, rows):
        """
        rows -> delete the rows from the dataset
        rows hold the row indices
        """
        deleteCount = 0
        rows = rows[:]
        rows.sort()

        for i in rows:
            self.data.pop(i-deleteCount)
            # we need to advance the delete count
            # to make sure we delete the right rows
            deleteCount += 1

    def SortColumn(self, col):
        """
        col -> sort the data based on the column indexed by col
        """
        name = self.colnames[col]
        _data = []

        for row in self.data:
            _data.append((row.get(name, None), row))

        _data.sort()
        self.data = []

        for sortvalue, row in _data:
            self.data.append(row)

    # end table manipulation code
    # ----------------------------------------------------------


# --------------------------------------------------------------------
# Sample wx.Grid renderers

class MegaImageRenderer(Grid.GridCellRenderer):
    def __init__(self, table):
        """
        Image Renderer Test.  This just places an image in a cell
        based on the row index.  There are N choices and the
        choice is made by  choice[row%N]
        """
        Grid.GridCellRenderer.__init__(self)
        self.table = table
        self._choices = [images.Smiles.GetBitmap,
                         images.Mondrian.GetBitmap,
                         images.WXPdemo.GetBitmap,
                         ]

        self.colSize = None
        self.rowSize = None

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        choice = self.table.GetRawValue(row, col)
        bmp = self._choices[ choice % len(self._choices)]()
        image = wx.MemoryDC()
        image.SelectObject(bmp)

        # clear the background
        dc.SetBackgroundMode(wx.SOLID)

        if isSelected:
            dc.SetBrush(wx.Brush(wx.BLUE, wx.BRUSHSTYLE_SOLID))
            dc.SetPen(wx.Pen(wx.BLUE, 1, wx.PENSTYLE_SOLID))
        else:
            dc.SetBrush(wx.Brush(wx.WHITE, wx.BRUSHSTYLE_SOLID))
            dc.SetPen(wx.Pen(wx.WHITE, 1, wx.PENSTYLE_SOLID))
        dc.DrawRectangle(rect)


        # copy the image but only to the size of the grid cell
        width, height = bmp.GetWidth(), bmp.GetHeight()

        if width > rect.width-2:
            width = rect.width-2

        if height > rect.height-2:
            height = rect.height-2

        dc.Blit(rect.x+1, rect.y+1, width, height,
                image,
                0, 0, wx.COPY, True)


class MegaFontRenderer(Grid.GridCellRenderer):
    def __init__(self, table, color="blue", font="ARIAL", fontsize=8):
        """Render data in the specified color and font and fontsize"""
        Grid.GridCellRenderer.__init__(self)
        self.table = table
        self.color = color
        self.font = wx.Font(fontsize, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, 0, font)
        self.selectedBrush = wx.Brush("blue", wx.BRUSHSTYLE_SOLID)
        self.normalBrush = wx.Brush(wx.WHITE, wx.BRUSHSTYLE_SOLID)
        self.colSize = None
        self.rowSize = 50

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        # Here we draw text in a grid cell using various fonts
        # and colors.  We have to set the clipping region on
        # the grid's DC, otherwise the text will spill over
        # to the next cell
        dc.SetClippingRegion(rect)

        # clear the background
        dc.SetBackgroundMode(wx.SOLID)

        if isSelected:
            dc.SetBrush(wx.Brush(wx.BLUE, wx.BRUSHSTYLE_SOLID))
            dc.SetPen(wx.Pen(wx.BLUE, 1, wx.PENSTYLE_SOLID))
        else:
            dc.SetBrush(wx.Brush(wx.WHITE, wx.BRUSHSTYLE_SOLID))
            dc.SetPen(wx.Pen(wx.WHITE, 1, wx.PENSTYLE_SOLID))
        dc.DrawRectangle(rect)

        text = self.table.GetValue(row, col)
        dc.SetBackgroundMode(wx.SOLID)

        # change the text background based on whether the grid is selected
        # or not
        if isSelected:
            dc.SetBrush(self.selectedBrush)
            dc.SetTextBackground("blue")
        else:
            dc.SetBrush(self.normalBrush)
            dc.SetTextBackground("white")

        dc.SetTextForeground(self.color)
        dc.SetFont(self.font)
        dc.DrawText(text, rect.x+1, rect.y+1)

        # Okay, now for the advanced class :)
        # Let's add three dots "..."
        # to indicate that that there is more text to be read
        # when the text is larger than the grid cell

        width, height = dc.GetTextExtent(text)

        if width > rect.width-2:
            width, height = dc.GetTextExtent("...")
            x = rect.x+1 + rect.width-2 - width
            dc.DrawRectangle(x, rect.y+1, width+1, height)
            dc.DrawText("...", x, rect.y+1)

        dc.DestroyClippingRegion()


# --------------------------------------------------------------------
# Sample Grid using a specialized table and renderers that can
# be plugged in based on column names

class wxdbGrid(Grid.Grid):
    def __init__(self, parent, data, colnames, rowlabelscol = None, plugins=None):
        """parent, data, colnames, plugins=None
        Initialize a grid using the data defined in data and colnames
        (see MegaTable for a description of the data format)
        plugins is a dictionary of columnName -> column renderers.
        """

        # The base class must be initialized *first*
        Grid.Grid.__init__(self, parent, -1)
        self._table = MegaTable(data, colnames, rowlabelscol, plugins)
        self.SetTable(self._table)
        self._plugins = plugins

        self.Bind(Grid.EVT_GRID_LABEL_RIGHT_CLICK, self.OnLabelRightClicked)

    def Reset(self):
        """reset the view based on the data in the table.  Call
        this when rows are added or destroyed"""
        self._table.ResetView(self)

    def OnLabelRightClicked(self, evt):
        # Did we click on a row or a column?
        row, col = evt.GetRow(), evt.GetCol()
        if row == -1: self.colPopup(col, evt)
        elif col == -1: self.rowPopup(row, evt)

    def rowPopup(self, row, evt):
        """(row, evt) -> display a popup menu when a row label is right clicked"""
        appendID = wx.NewIdRef()
        deleteID = wx.NewIdRef()
        x = self.GetRowSize(row)/2

        if not self.GetSelectedRows():
            self.SelectRow(row)

        menu = wx.Menu()
        xo, yo = evt.GetPosition()
        menu.Append(appendID, "Append Row")
        menu.Append(deleteID, "Delete Row(s)")

        def append(event, self=self, row=row):
            self._table.AppendRow(row)
            self.Reset()

        def delete(event, self=self, row=row):
            rows = self.GetSelectedRows()
            self._table.DeleteRows(rows)
            self.Reset()

        self.Bind(wx.EVT_MENU, append, id=appendID)
        self.Bind(wx.EVT_MENU, delete, id=deleteID)
        self.PopupMenu(menu)
        menu.Destroy()
        return


    def colPopup(self, col, evt):
        """(col, evt) -> display a popup menu when a column label is
        right clicked"""
        x = self.GetColSize(col)/2
        menu = wx.Menu()
        id1 = wx.NewIdRef()
        sortID = wx.NewIdRef()

        xo, yo = evt.GetPosition()
        self.SelectCol(col)
        cols = self.GetSelectedCols()
        self.Refresh()
        menu.Append(id1, "Delete Col(s)")
        menu.Append(sortID, "Sort Column")

        def delete(event, self=self, col=col):
            cols = self.GetSelectedCols()
            self._table.DeleteCols(cols)
            self.Reset()

        def sort(event, self=self, col=col):
            self._table.SortColumn(col)
            self.Reset()

        self.Bind(wx.EVT_MENU, delete, id=id1)

        if len(cols) == 1:
            self.Bind(wx.EVT_MENU, sort, id=sortID)

        self.PopupMenu(menu)
        menu.Destroy()
        return


class MegaFontRendererFactory:
    def __init__(self, color, font, fontsize):
        """
        (color, font, fontsize) -> set of a factory to generate
        renderers when called.
        func = MegaFontRenderFactory(color, font, fontsize)
        renderer = func(table)
        """
        self.color = color
        self.font = font
        self.fontsize = fontsize

    def __call__(self, table):
        return MegaFontRenderer(table, self.color, self.font, self.fontsize)

class MainWindow(wx.Frame):
    def __init__(self, parent, plugins):
        wx.Frame.__init__(self, parent, -1,
                         "Test Frame", size=(800,600))
        
        
        creds = dbCredentials()
        self.eng = create_engine('postgresql+psycopg2://{user}:{password}@{host}/{dbname}'.format(**creds))
        self.meta = MetaData(self.eng)
        self.con = self.eng.connect()         
 
        
        
        
        # tb_name = 'gm_articles'
        tb_name = 'covid_19'
        tb_query = Table(tb_name, self.meta, autoload=True) 
       
        # stm1 = select([tb_query])
        
        stm1 = select([
                            tb_query.c.codmun,
                            tb_query.c.data,                
                            func.sum(tb_query.c.casosAcumulado,type_=Integer)
                            ])
        estado = 'SP'
        stm1 = stm1.where(tb_query.c.estado == estado)
        stm1 = stm1.where(tb_query.c.codmun == None)
        stm1 = stm1.group_by(tb_query.c.codmun,tb_query.c.data)
        stm1 = stm1.order_by(tb_query.c.codmun,tb_query.c.data)


        data, colnames = self.QueryData(stm1)
        
        
        
        rowlabelscol = lambda row,nrow : str(nrow)
        coldays2double = lambda row, nrow : 0 if nrow == 1 else 0 if nrow == 2 else 0 if nrow == 3 else 0 if nrow == 4 else 0 if nrow == 5 else 0 if nrow == 6 else 7*ln(2)/(ln(data[nrow])-ln(data[nrow-6]))

        calc_fields= dict()

        calc_fields['Row'] = { "def": rowlabelscol }        
        calc_fields['Days2Double'] = { "def": coldays2double }        
        
        print(calc_fields)
        
              
        # print(data)
        # data = []
        grid = wxdbGrid(self, data, colnames,rowlabelscol, plugins)
        grid.Reset()


    def QueryData(self, query):     
        rs = self.con.execute(query)      
        colnames = rs.keys()
        rows = rs.fetchall()
        data =  [ dict(zip(colnames, row))  for row in rows ]
        # data = []  
        # nrow = 0
        # for row in rows: 
        #     line = {}
        #     ncol = 0
        #     for name in colnames:
        #         line[name] = row[name]
        #         ncol += 1                
        #     # data.append((str(nrow),line))
        #     data.append(line)
        #     nrow += 1
        return data,colnames

#class NewsGather(WxAsyncApp):
class NewsGather(wx.App):

    def twoSecondsPassed(self):
        print("two seconds passed")
        wx.CallLater(2000, self.twoSecondsPassed)

    def OnInit(self):
                
        window = MainWindow(None, "wxdbGrid test!")
        window.Show()
        self.SetTopWindow(window)
        # look, we can use twisted calls!
        wx.CallLater(2000, self.twoSecondsPassed)
        return True

if __name__ == '__main__':
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    
#    handler = logging.StreamHandler(sys.stdout)
#    handler.setLevel(logging.DEBUG)
#    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#    handler.setFormatter(formatter)
#    root.addHandler(handler)   # register the App instance with Twisted:



    app = NewsGather(0)
    app.MainLoop()
    
    # start the event loop:
#    loop = get_event_loop()
#    loop.run_until_complete()



