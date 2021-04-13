#!/usr/bin/python3.5 -u
import os
import sys
import argparse
import subprocess
import xattr
import re
import hashlib


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


def dir_size(start_path):
    total_size = 0
    for element in os.listdir(start_path):
        pathname=os.path.join(start_path, element)
        #skip links and mountpoints, recurse dirs
        if not os.path.islink(pathname):
            if os.path.isfile(pathname):
                total_size += os.path.getsize(pathname)
            elif os.path.isdir(pathname): 
                if not os.path.ismount(pathname):
                    total_size += dir_size(pathname)
    return total_size

units = {None: 1, "B": 1, "KB": 2**10, "MB": 2**20, "GB": 2**30, "TB": 2**40}

def parse_size(size):
    size = size.upper()
    if not re.match(r' ', size):
        size = re.sub(r'([KMGT]?B)', r' \1', size)
    number, unit = [string.strip() for string in size.split()]
    return int(float(number)*units[unit])

def md5sum(file):
    md5_hash=hashlib.md5()
    with open (file,'rb') as f:
        for byte_block in iter(lambda: f.read(4096),b""):
            md5_hash.update(byte_block)
        return(md5_hash.hexdigest())

def find_file_collisions(path):
    source=[]
    mergerfs=list_mergerfs()
    for root, dirs, files in os.walk(path):
        for name in files:
            source2=[]
            target=os.path.normpath(os.path.join(root, name))
            if os.path.isfile(target) and not os.path.islink(target): 
                absolute=os.path.abspath(target)
                mountpoint=find_mountpoint(absolute)
                if str(mountpoint) in mergerfs.keys():
                    relative=os.path.relpath(absolute,start=mountpoint)
                    for branch in mergerfs[mountpoint]:
                        path=os.path.join(branch,relative)
                        if os.path.exists(path):
                            source2.append(path)
            if len(source2) > 1:
                source.append(source2)
    if len(source) > 0 :
        return(source)
    else:
        return(None)
        



def main():
    parser = argparse.ArgumentParser(description='Consolidate mergerfs files present in multiple branches into one.')
    parser.add_argument('-m','--minspace',help='Minimum space in the filesystem (Accepts suffixes: None, B, KB, MB, GB, TB)', default='400GB')
    parser.add_argument('-c','--collision',help="Action on file collision between branches. abort: abort consolidation; identical: deduplicate identical branches; ignore: ignores existing files", default='identical')
    parser.add_argument('-d','--dryrun',help='Dry run - do not move files', action='store_true', default=False)
    parser.add_argument('filenames', nargs='+', help='Directory or directories to check')
    args=parser.parse_args()
    
    minsize_bytes=parse_size(args.minspace)
    
    mergerfs=list_mergerfs()
    for i in args.filenames:
        target=os.path.normpath(i)
        collisions=find_file_collisions(target)
        if os.path.isdir(target) and not (os.path.islink(target) or os.path.ismount(target)): 
            targetsize=dir_size(target)
            absolute=os.path.abspath(target)
            mountpoint=find_mountpoint(absolute)
            source=[]
            if str(mountpoint) in mergerfs.keys():
                relative=os.path.relpath(absolute,start=mountpoint)
                for branch in mergerfs[mountpoint]:
                    branchdict={}
                    branchdict['branch']=branch
                    branchdict['relative']=relative
                    branchdict['path']=os.path.join(branch,relative)
                    branchdict['freespace']=os.statvfs(branchdict['branch']).f_bavail * os.statvfs(branchdict['branch']).f_frsize
                    branchdict['isbranch']=False
                    branchdict['branchsize']=0
                    branchdict['branchpath']=''
                    if os.path.exists(os.path.join(branch,relative)) and os.path.isdir(os.path.join(branch,relative)) and not (os.path.islink(os.path.join(branch,relative)) or os.path.ismount(os.path.join(branch,relative)) ):
                        branchdict['isbranch']=True
                        branchdict['branchpath']=os.path.join(branch,relative)
                        branchdict['branchsize']=dir_size(branchdict['branchpath'])
                    source.append(branchdict)
            #find optimal branch for consolidation
            consolidation_freespace=None
            consolidation_branch=None
            consolidation_newbranch=None
            for i,j in enumerate(source):
                if j['isbranch']:
                    free_space_test=j['freespace'] - targetsize + j['branchsize']
                    if free_space_test > minsize_bytes: 
                    #move everything to branch with least free space
                        if (not consolidation_freespace) or free_space_test < consolidation_freespace:
                            consolidation_branch=source[i]
                            consolidation_freespace=free_space_test
            if consolidation_branch is None:
                for i,j in enumerate(source):
                    if not j['isbranch']:
                        free_space_test=j['freespace'] - targetsize + j['branchsize']
                        if free_space_test > minsize_bytes:
                        #if a new branch has to be created, use fs with least free space
                            if (not consolidation_freespace) or free_space_test < consolidation_freespace:
                                consolidation_branch=source[i]
                                consolidation_freespace=free_space_test
                                consolidation_newbranch=True
            if consolidation_newbranch:
                if args.dryrun:
                    print('No space in existing branches! (dry run) Creating new one in '+consolidation_branch['branchpath'])
                else:
                    print('No space in existing branches! (dry run) Creating new one in '+consolidation_branch['branchpath'])
                    os.makedirs(consolidation_branch['branchpath'], exist_ok=True)
            if consolidation_branch is None:
                print('No free space!!!')
            else:
                #print(source[consolidation_branch])
                if args.collision=="abort":
                    if collisions is not None:
                        print("File collisions found!!!")
                        print(collisions)
                        continue
                if args.collision=="identical":
                    if collisions is not None:
                        print(collisions)
                        for i in collisions:
                            hash=None
                            match=False
                            for j in i:
                                if not hash:
                                    hash=md5sum(j)
                                    print(j+' '+hash)
                                else:
                                    nexthash=md5sum(j)
                                    if hash==nexthash:
                                        match=True
                                        if args.dryrun:
                                            print('Removing (dry run)... ' + j+' '+nexthash)
                                        else:
                                            print('Removing... ' + j+' '+nexthash)
                                            if os.path.isfile(j):
                                                os.remove(j)
                                            
                                    else:
                                        match=False
                                        print(j+' '+nexthash)
                                        break
                            if not match:
                                print("Collision with different files!!!")
                print("Rsync...")
                destination=os.path.join(os.path.normpath(os.path.join(consolidation_branch['branchpath'],'..')),'')
                for i in source:
                    if i['isbranch']:
                        if i['branch']!=consolidation_branch['branch']:
                            #print('rsync -aPx --dry-run --ignore-existing --remove-source-files ' + os.path.join(i['branchpath'])+' '+ destination)
                            #print('find '+ os.path.join(i['branchpath']) + ' -type d -empty -delete ')
                            if args.dryrun:
                                try:
                                    rsync_command_dryrun=['rsync', '-a', '-P', '-x', '-i', '--ignore-existing', '--remove-source-files', '--dry-run', os.path.join(i['branchpath']), destination]
                                    find_clean_command_dryrun=['find', os.path.join(i['branchpath']), '-type', 'd', '-empty' ]
                                    print("Moving (dry run)... "+os.path.join(i['branchpath'])+' -> '+ destination)
                                    rsync_process=subprocess.run(rsync_command_dryrun, stdin=None, shell=False, check=True)
                                    print("Deleting empty folders (dry run)... "+os.path.join(i['branchpath']))
                                    find_clean_process=subprocess.run(find_clean_command_dryrun, stdin=None, shell=False, check=True)
                                    #print(f)
                                except subprocess.CalledProcessError as e:
                                    print(e.output)
                                    print(e.returncode)
                                    test_list.remove(i)
                                    continue
                            else:
                                try:
                                    rsync_command=['rsync', '-a', '-P', '-x', '--ignore-existing', '--remove-source-files', os.path.join(i['branchpath']), destination]
                                    find_clean_command=['find', os.path.join(i['branchpath']), '-type', 'd', '-empty', '-delete' ]
                                    print("Moving... "+os.path.join(i['branchpath'])+' -> '+ destination)
                                    rsync_process=subprocess.run(rsync_command, stdin=None, shell=False, check=True)
                                    print("Deleting empty folders... "+os.path.join(i['branchpath']))
                                    find_clean_process=subprocess.run(find_clean_command, stdin=None, shell=False, check=True)
                                    #print(f)
                                except subprocess.CalledProcessError as e:
                                    print(e.output)
                                    print(e.returncode)
                                    test_list.remove(i)
                                    continue



main()
