#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import wx 
import urllib.request 
import json
import webbrowser

API_KEY = '4327173775a746e9b4f2632af3933a86'

class NewsPanel1(wx.Panel):

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.SetBackgroundColour("gray")


class NewsPanel(wx.Panel):

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.SetBackgroundColour("gray")

        self.sources_list = wx.ListCtrl(
            self, 
            style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        self.sources_list.InsertColumn(0, "Source", width=200)
        
        self.news_list = wx.ListCtrl(
            self, 
            size = (-1 , - 1),
            style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        self.news_list.InsertColumn(0, 'Link')
        self.news_list.InsertColumn(1, 'Title')
        
        
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.sources_list, 0, wx.ALL | wx.EXPAND)
        sizer.Add(self.news_list, 1, wx.ALL | wx.EXPAND)
        
        self.SetSizer(sizer)
        self.getNewsSources()
        self.sources_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnSourceSelected)
        self.news_list.Bind(wx.EVT_LIST_ITEM_SELECTED , self.OnLinkSelected)
        
        self.Bind(wx.EVT_PAINT, self.OnPaint)
    
    def OnPaint(self, evt):
        width, height = self.news_list.GetSize()
        for i in range(2):
            self.news_list.SetColumnWidth(i, width/2)
        evt.Skip()
    
    def OnSourceSelected(self, event):
         source = event.GetText().replace(" ", "-")
         print(source)
         self.getNews(source)
    
    
    def OnLinkSelected(self, event):
          print(event.GetText()) 
          webbrowser.open(event.GetText())           

         
    def getNews(self, source):
         with urllib.request.urlopen("https://newsapi.org/v2/top-headlines?sources="+ source + "&apiKey=" + API_KEY) as response:
             response_text = response.read()   
             encoding = response.info().get_content_charset('utf-8')
             JSON_object = json.loads(response_text.decode(encoding))    
             self.news_list.DeleteAllItems()
             index = 0
             for el in JSON_object["articles"]:
                 self.news_list.InsertItem(index, el["url"])
                 self.news_list.SetItem(index, 1, el["title"])
                 index += 1
                         
    def getNewsSources(self):
        with urllib.request.urlopen("https://newsapi.org/v2/sources?language=en&apiKey=" + API_KEY) as response:
            response_text = response.read()   
            encoding = response.info().get_content_charset('utf-8')
            JSON_object = json.loads(response_text.decode(encoding))            
            
            #return JSON_object
            
            #print( JSON_object["sources"] )
            for el in JSON_object["sources"]:
                 print(el["description"] + ":")
                 print(el["id"] + ":")
                 
                 print(el["url"] + "\n")
                 self.sources_list.InsertItem(0, el["name"])
                

class MainWindow(wx.Frame):
    def __init__(self, parent, title):

        super(MainWindow, self).__init__(parent, title = title, size = (600,500))
        self.Centre()

        NewsPanel(self)
        #self.panel.SetBackgroundColour("gray")
        self.createStatusBar()
        self.createMenu()
        
    def createStatusBar(self):
        self.CreateStatusBar() #A Statusbar at the bottom of the window


    def createMenu(self):
    
        menu= wx.Menu()
        menuExit = menu.Append(wx.ID_EXIT, "E&xit", "Quit application")

        menuBar = wx.MenuBar()
        menuBar.Append(menu,"&File")
        self.SetMenuBar(menuBar)

        self.Bind(wx.EVT_MENU, self.OnExit, menuExit)

    def OnExit(self, event):
        self.Close(True) 


if __name__ == '__main__':
    app = wx.App()
    window = MainWindow(None, "Newsy - read worldwide news!")
    window.Show()
    app.MainLoop()
