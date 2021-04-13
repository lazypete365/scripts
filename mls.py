#!/usr/bin/python3.5 -u
import os
import sys
import argparse
import subprocess
import xattr
import re

RED='\033[0;31m'
NC='\033[0m'

def find_mountpoint(path):
    mountpoint=subprocess.run(['stat', '-c', '%m', '--', path],stdout=subprocess.PIPE, shell=False, check=True).stdout.decode('utf8').replace('\n', '').replace('\r', '')
    return mountpoint

def list_mergerfs():
    mergerfs=re.compile(r'^[^ ]* (.*) fuse\.mergerfs.*')
    sanitize=re.compile(r'=[^:]*')
    mountpoint={}
    with open('/proc/mounts','r') as mounts:
        for line in mounts.read().splitlines():
            (point, match)=re.subn(mergerfs,'\g<1>',line)
            if match==1:
                mountpoint[point]=re.sub(sanitize,'',xattr.get(os.path.join(point,'.mergerfs'),'user.mergerfs.branches').decode('utf-8')).split(':')
    return mountpoint

def main():
    parser = argparse.ArgumentParser(description='Find mergerfs files present in multiple branches')
    parser.add_argument('-q','--quiet',help='Only outputs files present in multiple branches, no colour', action='store_true', default=False)
    parser.add_argument('-d','--directories',help='List only directories', action='store_true', default=False)
    parser.add_argument('-f','--files',help='List only files', action='store_true', default=False)
    parser.add_argument('filenames', nargs='+', help='File or files to check')
    args=parser.parse_args()
    
    mergerfs=list_mergerfs()
    for i in args.filenames:
        target=os.path.normpath(i)
        if (args.files==False and args.directories==False) or ( args.files==True and os.path.isfile(target) ) or ( args.directories==True and os.path.isdir(target)): 
            absolute=os.path.abspath(target)
            mountpoint=find_mountpoint(absolute)
            if str(mountpoint) in mergerfs.keys():
                relative=os.path.relpath(absolute,start=mountpoint)
                source=[]
                for branch in mergerfs[mountpoint]:
                    path=os.path.join(branch,relative)
                    if os.path.exists(path):
                        source.append(path)
                if len(source) > 1 and args.quiet==False:
                    print(RED+absolute+'\t'+':'.join(source)+NC)
                elif len(source) > 1 and args.quiet==True:
                    print(absolute+'\t'+':'.join(source))
                elif args.quiet==False:
                    print(absolute.encode('utf-8', 'replace').decode()+'\t'+str(':'.join(source).encode('utf-8', 'replace').decode()))

main()
