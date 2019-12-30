#!/usr/bin/python3
import sqlite3
from datetime import datetime, timedelta

import lz4.block
import sys
import json
import os
import subprocess
from glob import glob
from argparse import ArgumentParser as argparse
import time


delim='\t'


def ff_history(db_file):
    #returns a dictionary with the parsed history entries and the starting and ending dates of the history file
    if not os.path.isfile(db_file):
        raise Exception('DB file not found at path: {}'.format(db_file))
    with sqlite3.connect('file:'+db_file+'?immutable=1', uri=True) as history_db:
        cursor=history_db.cursor()
        cursor.execute("SELECT visit_date, url, title FROM moz_historyvisits JOIN moz_places ON moz_historyvisits.place_id=moz_places.id;")
        history_raw=cursor.fetchall()
        cursor.close()
    
    history={}
    for element in history_raw:
        date=element[0]/1000000 #to convert weird ff epoch to unix standard epoch
        date_hr=datetime.fromtimestamp(date).strftime('%Y-%m-%d %H:%M:%S')
        year=date_hr[:4]
        if year not in history:
            history[year]={"history":[],"date_min":99999999999, "date_max":0}
        if date<history[year]["date_min"]: 
            history[year]["date_min"]=date
        if date>history[year]["date_max"]: 
            history[year]["date_max"]=date
        site=str(element[1])
        title=str(element[2]) #will have to replace delims later on output .replace(delim, ' ')
        history[year]["history"].append([date, date_hr, site.replace(delim, ' '), title.replace(delim, ' ')])
    return history
    
def com_hist(hist_file, hist_year):
    clean_old=[]
    hist_year_hashable=[]
    for i in hist_year:
        #print(i)
        line=('\t'.join(str(j) for j in i)+'\n')
        if not line.isspace():
            hist_year_hashable.append(line)
    with open(hist_file,'r') as old_hist:
        for line in old_hist:
            if not line.isspace():
                clean_old.append(line)
    difference=set(hist_year_hashable)-set(clean_old)
    merger=set(hist_year_hashable)|set(clean_old)
    merger_split=[]
    if not not merger:
        for i in merger:
            merger_split.append(i.split('\t'))
    return [difference,merger_split]
def ff_bookmarks(db_file):
    if not os.path.isfile(db_file):
        raise Exception('DB file not found at path: {}'.format(db_file))
    with sqlite3.connect('file:'+db_file+'?immutable=1', uri=True) as bookmark_db:
        cursor=bookmark_db.cursor()
        cursor.execute("""
        SELECT moz_bookmarks.id, moz_bookmarks.type, moz_places.url, moz_bookmarks.title, moz_bookmarks.dateAdded, moz_bookmarks.lastModified, moz_bookmarks.keyword_id, moz_keywords.keyword, moz_keywords.place_id, moz_bookmarks.parent, b.title
        FROM moz_bookmarks LEFT OUTER JOIN moz_places ON moz_bookmarks.fk=moz_places.id 
        LEFT OUTER JOIN moz_keywords ON moz_bookmarks.fk=moz_keywords.place_id
        LEFT OUTER JOIN moz_bookmarks AS b ON moz_bookmarks.parent=b.id
        ;
        """)
        bookmarks_raw=cursor.fetchall()
        cursor.close()

    def bookmark_path(id):
        if bookmarks[id]["parentid"] in bookmarks.keys() and bookmarks[id]["parentid"] != 1:
            return_path=bookmark_path(bookmarks[id]["parentid"])+str(bookmarks[bookmarks[id]["parentid"]]["title"])+'/'
        elif bookmarks[id]["parentid"] in bookmarks.keys() and bookmarks[id]["parentid"] == 1:
            return_path="root/"
        else:
            return_path="root"
        return return_path
    bookmarks={}
    bookmarks_date=0
    bookmark_type=["none","bookmark","tag","separator","dynamic"]
    for element in bookmarks_raw:
        bookmark_id=element[0]
        bookmarks[bookmark_id]={
            "type":bookmark_type[element[1]],
            "url":str(element[2]), 
            "title":str(element[3]), ##will have to replace delims later on output .replace(delim, ' ')
            "parentid":element[9], 
            "date_added":element[4]/1000000, 
            "date_added_hr":datetime.fromtimestamp(element[4]/1000000).strftime('%Y-%m-%d %H:%M:%S'), 
            "date_modified":element[5]/1000000, 
            "date_modified_hr":datetime.fromtimestamp(element[5]/1000000).strftime('%Y-%m-%d %H:%M:%S'), 
            "keyword_id":element[6],
            "keyword":element[7],
            "keyword_place_id":element[8],
            "parent_title":str(element[10]) ##will have to replace delims later on output .replace(delim, ' ')
            }
    for i in bookmarks:
        bookmarks[i]["path"]=bookmark_path(i)
        if bookmarks[i]["date_modified"]>bookmarks_date:
            bookmarks_date=bookmarks[i]["date_modified"]

    return {"bookmarks":bookmarks, "bookmarks_date":bookmarks_date}
    
def ff_tabs(session_file):
    if not os.path.isfile(session_file):
        raise Exception('Session file not found at path: {}'.format(session_file))
    with open(session_file, "rb") as in_file:
        if in_file.read(8) != b"mozLz40\0":
            raise InvalidHeader("Invalid magic number")
        session_data=json.loads(lz4.block.decompress(in_file.read()))

    session_date=0
    tabs=[]
    for i in range(len(session_data["windows"])):
        for j in range(len(session_data["windows"][i]["tabs"])):
            if len(session_data["windows"][i]["tabs"][j]["entries"])>0:
                taburl=str(session_data["windows"][i]["tabs"][j]["entries"][0]["url"])
                tabtitle=str(session_data["windows"][i]["tabs"][j]["entries"][0]["title"])
            elif "userTypedValue" in session_data["windows"][i]["tabs"][j]:
                taburl=str(session_data["windows"][i]["tabs"][j]["userTypedValue"])
                tabtitle=taburl
            if int(session_data["windows"][i]["tabs"][j]["lastAccessed"])/1000 > session_date :
                session_date=int(session_data["windows"][i]["tabs"][j]["lastAccessed"])/1000
            tabs.append({"window":i,"url":taburl, "title":tabtitle})

    return {"tabs":tabs, "session_date":session_date}


def parse_places(db_file,backup_target,profile_name):
    if os.path.isfile(db_file):
        print("places.sqlite found! Parsing bookmarks and history...")
        history=ff_history(db_file)
        print('history parsed!')
        for i in history.values():
            base_filename=os.path.join(backup_target,profile_name+'.hist.'+datetime.fromtimestamp(i["date_min"]).strftime('%Y%m%d%H%M%S')+'_'+datetime.fromtimestamp(i["date_max"]).strftime('%Y%m%d%H%M%S'))
            glob_name=os.path.join(backup_target,profile_name+'.hist.'+datetime.fromtimestamp(i["date_min"]).strftime('%Y%m%d%H%M%S')+'_??????????????.txt')
            glob_name2=os.path.join(backup_target,profile_name+'.hist.'+'??????????????_'+datetime.fromtimestamp(i["date_max"]).strftime('%Y%m%d%H%M%S')+'.txt')
            if os.path.isfile(base_filename+'.txt'):
                comparison=com_hist(base_filename+'.txt', i["history"])
                if not comparison[0]==set():
                    print("An older history file exists but is different for some reason; attempting merge")
                    merged=sorted(comparison[1], key=lambda k:(k[0], k[2]))
                    with open(base_filename+'.tmp','w') as tempfile:
                        for j in merged:
                            tempfile.write('\t'.join(j))
                    os.remove(base_filename+'.txt')
                    os.rename(base_filename+'.tmp',base_filename+'.txt')
                else:
                    print("An older history file exists and is identical; maintaining unchanged")
            elif glob(glob_name):
                old_filename=glob(glob_name)[0]
                print("History file found with matching start date; trying to append new history")
                print(old_filename)
                comparison=com_hist(old_filename, i["history"])
                if not comparison[0]==set():
                    print("Found changes, attempting merge")
                    merged=sorted(comparison[1], key=lambda k:(k[0], k[2]))
                    with open(base_filename+'.tmp','w') as tempfile:
                        for j in merged:
                            tempfile.write('\t'.join(j))
                    os.rename(base_filename+'.tmp',base_filename+'.txt')
                    os.remove(old_filename)
                else:
                    print("No changes found")
            elif glob(glob_name2):
                old_filename=glob(glob_name2)[0]
                print("History file found with matching end date; trying to append new history")
                print(old_filename)
                comparison=com_hist(old_filename, i["history"])
                if not comparison[0]==set():
                    print("Found changes, attempting merge")
                    merged=sorted(comparison[1], key=lambda k:(k[0], k[2]))
                    new_date_min=99999999999999
                    new_date_max=0
                    with open(base_filename+'.tmp','w') as tempfile:
                        for j in merged:
                            if float(j[0])>new_date_max:
                                new_date_max=float(j[0])
                            if float(j[0])<new_date_min:
                                new_date_min=float(j[0])
                            tempfile.write('\t'.join(j))
                    
                    new_timestamped_filename=os.path.join(backup_target,profile_name+'.hist.'+datetime.fromtimestamp(int(new_date_min)).strftime('%Y%m%d%H%M%S')+'_'+datetime.fromtimestamp(int(new_date_max)).strftime('%Y%m%d%H%M%S'))
                    print(new_timestamped_filename)
                    print(old_filename)
                    os.remove(old_filename)
                    time.sleep(10)
                    os.rename(base_filename+'.tmp',new_timestamped_filename+'.txt')

                else:
                    print("No changes found")
            else:
                print("No existing history file found; creating new history file")
                merged=sorted(i["history"], key=lambda k:(k[0], k[2]))
                with open(base_filename+'.txt','w') as tempfile:
                    for j in merged:
                        tempfile.write('\t'.join(str(k) for k in j)+'\n')
        print("history written!")
        bookmarks=ff_bookmarks(db_file)
        print('bookmarks parsed!')
        bookmarks_date_human=datetime.fromtimestamp(bookmarks["bookmarks_date"]).strftime('%Y%m%d%H%M%S')
        with open(os.path.join(backup_target,profile_name+'.bookmarks.'+bookmarks_date_human+'.txt'),'w') as bookmarks_outfile:
            for i in sorted(bookmarks["bookmarks"].items(), key= lambda x: str(x[1]["path"])):
                line=(
                i[1]["path"]+
                delim+
                i[1]["url"]+
                delim+
                i[1]["title"]+
                delim+
                i[1]["type"]+
                delim+
                i[1]["date_modified_hr"]+
                delim+
                str(i[1]["keyword"])+
                delim+
                str(i[0])+
                delim+
                str(i[1]["parentid"])+
                delim+
                i[1]["parent_title"]
                )
                bookmarks_outfile.write(line+'\n')
        print('bookmarks written!')
def parse_session(session_file, backup_target, profile_name):
    if os.path.isfile(session_file):
        print("Session file found! Parsing tabs...")
        tabs=ff_tabs(session_file)
        print('tabs parsed!')
        session_date_human=datetime.fromtimestamp(tabs["session_date"]).strftime('%Y%m%d%H%M%S')
        with open(os.path.join(backup_target,profile_name+'.tabs.'+session_date_human+'.txt'),'w') as session_outfile:
            for i in tabs["tabs"]:
                line=(
                    str(i["window"])+
                    delim+
                    i["url"].replace(delim, ' ')+
                    delim+
                    i["title"].replace(delim, ' ')
                    )
                session_outfile.write(line+'\n')
        print('tabs written!')
        
parser = argparse(description="Testing arguments")
parser.add_argument('--config_path', '-c', type=str, help="Path to config folder")
parser.add_argument('--profile_name', '-p', type=str, help="Profile name")
parser.add_argument('--all_profiles', '-a', action="store_true", default=False, help="Parse all profiles in config folder")
parser.add_argument('--output', '-o', type=str, help="Path to output files")
parser.add_argument('--single_profile', '-s', type=str, help="Path to single profile")
parser.add_argument('--places', type=str, help="Direct path to places.sqlite")
parser.add_argument('--session', type=str, help="Direct path to session file")

arguments=parser.parse_args()
if arguments.config_path!=None and arguments.all_profiles==True:
    print("Searching all profiles in config folder...")
elif arguments.config_path!=None and arguments.profile_name!=None:
    print("Searching profile "+arguments.profile_name)
    profile_name=arguments.profile_name
    config_path=arguments.config_path
    backup_target=arguments.output
    db_file=os.path.join(config_path, profile_name, 'places.sqlite')
    if os.path.isfile(db_file):
        parse_places(db_file, backup_target, profile_name)
    session_file=os.path.join(config_path, profile_name, 'sessionstore-backups','recovery.jsonlz4')
    if os.path.isfile(session_file):
        parse_session(session_file, backup_target, profile_name)
